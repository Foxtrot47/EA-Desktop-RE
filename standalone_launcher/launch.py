"""Launch installed EA titles without starting EA Desktop.

This implements the run-to-play date code used by the current EA Desktop and
legacy ActivationUI binaries.  It does not mint, alter, or replace a game
license; protected titles still validate their normal locally cached license.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from .finalize import windows_command_line_to_argv
from .install import InstallError, safe_relative_path
from .manifest import RuntimeLauncher, parse_dip_manifest


RTP_ENVIRONMENT_NAME = "EARtPLaunchCode"
DEFAULT_MANIFEST_PATH = Path("__Installer") / "installerdata.xml"

# Native title switches confirmed from shipped binaries and live process tests.
# Keys are (content ID, DiP launcher UID); values are appended after manifest
# parameters.  These switches alter only title UI flow, never license handling.
KNOWN_LAUNCH_ARGUMENTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("1019521", "2-2"): ("nolauncher",),
}


class LaunchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedLauncher:
    uid: str
    name: str
    executable: Path
    arguments: tuple[str, ...]
    execute_elevated: bool
    content_id: str | None = None


def generate_rtp_launch_code(when: date | None = None) -> str:
    """Return the unsigned 32-bit run-to-play code for a UTC calendar date."""
    if when is None:
        when = datetime.now(timezone.utc).date()
    value = (
        (104729 * when.year)
        ^ (350377 * when.day)
        ^ (224737 * when.month)
    ) & 0xFFFFFFFF
    code = (value ^ ((value << 16) & 0xFFFFFFFF) ^ (value >> 16)) & 0xFFFFFFFF
    return str(code)


def build_launch_environment(
    base: Mapping[str, str] | None = None,
    *,
    when: date | None = None,
    content_id: str | None = None,
) -> dict[str, str]:
    """Copy an environment and add the DiP identity and local RTP launch code."""
    environment = dict(os.environ if base is None else base)
    environment[RTP_ENVIRONMENT_NAME] = generate_rtp_launch_code(when)
    if content_id is not None:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", content_id):
            raise LaunchError("invalid content ID for game environment")
        environment["ContentId"] = content_id
    return environment


def _launcher_name(launcher: RuntimeLauncher, locale: str) -> str:
    return (
        launcher.names.get(locale)
        or launcher.names.get("en_US")
        or next(iter(launcher.names.values()), "")
        or launcher.uid
    )


def _launcher_relative_path(value: str) -> Path:
    """Reduce an EA registry-prefixed launcher path to its install-root suffix."""
    path = value.strip()
    if path.startswith("["):
        closing = path.rfind("]")
        if closing < 0:
            raise LaunchError(f"invalid registry-prefixed launcher path: {value!r}")
        path = path[closing + 1 :].lstrip("/\\")
    if not path:
        raise LaunchError("launcher path is empty")
    try:
        return safe_relative_path(path)
    except InstallError as exc:
        raise LaunchError(str(exc)) from None


def _launcher_score(launcher: RuntimeLauncher, locale: str) -> tuple[int, int, str]:
    text = f"{_launcher_name(launcher, locale)} {launcher.file_path}".casefold()
    configuration = any(word in text for word in ("setup", "config", "configuration"))
    return (1 if launcher.trial else 0, 1 if configuration else 0, launcher.uid.casefold())


def resolve_installed_launcher(
    install_location: Path | str,
    *,
    launcher_uid: str | None = None,
    locale: str = "en_US",
    manifest_path: Path | str | None = None,
) -> ResolvedLauncher:
    """Resolve a launchable executable from an installed DiP manifest."""
    root = Path(install_location).resolve()
    source = Path(manifest_path) if manifest_path is not None else root / DEFAULT_MANIFEST_PATH
    if not source.is_file():
        raise LaunchError(f"installed DiP manifest is missing: {source}")
    manifest = parse_dip_manifest(source.read_bytes())
    launchers = list(manifest.launchers)
    if launcher_uid is not None:
        launchers = [value for value in launchers if value.uid.casefold() == launcher_uid.casefold()]
        if not launchers:
            raise LaunchError(f"launcher UID {launcher_uid!r} is not in {source}")
    else:
        launchers.sort(key=lambda value: _launcher_score(value, locale))

    missing: list[Path] = []
    for launcher in launchers:
        executable = (root / _launcher_relative_path(launcher.file_path)).resolve()
        try:
            executable.relative_to(root)
        except ValueError:
            raise LaunchError("launcher executable escapes the install root") from None
        if not executable.is_file():
            missing.append(executable)
            continue
        compatibility_arguments: tuple[str, ...] = ()
        for content_id in manifest.content_ids:
            compatibility_arguments = KNOWN_LAUNCH_ARGUMENTS.get(
                (content_id, launcher.uid),
                compatibility_arguments,
            )
        return ResolvedLauncher(
            uid=launcher.uid,
            name=_launcher_name(launcher, locale),
            executable=executable,
            arguments=(
                *windows_command_line_to_argv(launcher.parameters),
                *compatibility_arguments,
            ),
            execute_elevated=launcher.execute_elevated,
            content_id=manifest.content_ids[0] if manifest.content_ids else None,
        )
    if missing:
        raise LaunchError(f"manifest launcher executable is missing: {missing[0]}")
    raise LaunchError(f"DiP manifest contains no launchers: {source}")


def launch_executable(
    executable: Path | str,
    arguments: Sequence[str] = (),
    *,
    working_directory: Path | str | None = None,
    when: date | None = None,
    content_id: str | None = None,
) -> subprocess.Popen[bytes]:
    """Start a game with the standalone RTP environment and no EA client IPC."""
    target = Path(executable).resolve()
    if not target.is_file():
        raise LaunchError(f"game executable is missing: {target}")
    cwd = Path(working_directory).resolve() if working_directory is not None else target.parent
    try:
        return subprocess.Popen(
            [str(target), *arguments],
            cwd=str(cwd),
            env=build_launch_environment(when=when, content_id=content_id),
            shell=False,
        )
    except OSError as exc:
        raise LaunchError(f"could not start {target.name}: {exc}") from None


def launch_installed_game(
    install_location: Path | str,
    *,
    launcher_uid: str | None = None,
    locale: str = "en_US",
) -> tuple[ResolvedLauncher, subprocess.Popen[bytes]]:
    launcher = resolve_installed_launcher(
        install_location,
        launcher_uid=launcher_uid,
        locale=locale,
    )
    process = launch_executable(
        launcher.executable,
        launcher.arguments,
        working_directory=Path(install_location),
        content_id=launcher.content_id,
    )
    return launcher, process
