"""Normal launch routing; BFN uses a detached supervisor for its tested helpers."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading

from .launch import LaunchError, ResolvedLauncher, launch_executable, resolve_installed_launcher
from .console_trace import start_trace_forwarder


ROOT = Path(__file__).resolve().parents[1]
BFN_CONTENT_ID = "194814"


def _startup_status(process: subprocess.Popen, timeout: float = 120) -> dict:
    ready = threading.Event()
    lines: list[str] = []

    def read_status() -> None:
        try:
            lines.append(process.stdout.readline(4096))
        finally:
            ready.set()

    threading.Thread(target=read_status, daemon=True).start()
    if not ready.wait(timeout):
        raise LaunchError("BFN session startup timed out; no launch was authorized")
    try:
        status = json.loads(lines[0])
    except (IndexError, ValueError):
        raise LaunchError("BFN session supervisor exited without a startup result") from None
    if not isinstance(status, dict) or status.get("ok") is not True:
        message = status.get("message") if isinstance(status, dict) else None
        raise LaunchError(message or "BFN standalone session could not start")
    process.stdout.close()
    return status


def _start_bfn_session(location: Path, launcher: ResolvedLauncher, locale: str, *, trace: bool = False) -> subprocess.Popen:
    command = [sys.executable, "-m", "standalone_launcher.bfn_session", str(location.resolve()),
               "--launcher-uid", launcher.uid, "--locale", locale]
    if trace:
        command.append("--trace")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if trace else subprocess.DEVNULL,
            text=True, encoding="utf-8", creationflags=flags,
        )
    except OSError:
        raise LaunchError("Could not start the BFN session supervisor") from None
    if trace:
        process._ea_trace_thread = start_trace_forwarder(process.stderr)
    try:
        _startup_status(process)
        process.stdin.write("launch\n")
        process.stdin.flush()
    except (OSError, ValueError):
        raise LaunchError("BFN session supervisor stopped before launch") from None
    finally:
        # EOF cancels startup if the caller times out/closes before sending the
        # launch command. After authorization, caller exit never stops the game.
        process.stdin.close()
    return process


def launch_game(
    install_location: Path | str, *, launcher_uid: str | None = None, locale: str = "en_US", trace: bool = False
) -> tuple[ResolvedLauncher, subprocess.Popen]:
    """Start BFN's managed session, or preserve direct launching for other games.

    The returned BFN process is its supervisor, not the short-lived EAAC launcher.
    Waiting for it waits until the game exits and owned helpers are cleaned up.
    """
    location = Path(install_location)
    launcher = resolve_installed_launcher(location, launcher_uid=launcher_uid, locale=locale)
    if launcher.content_id == BFN_CONTENT_ID:
        if trace:
            return launcher, _start_bfn_session(location, launcher, locale, trace=True)
        return launcher, _start_bfn_session(location, launcher, locale)
    return launcher, launch_executable(
        launcher.executable, launcher.arguments, working_directory=location,
        content_id=launcher.content_id,
    )
