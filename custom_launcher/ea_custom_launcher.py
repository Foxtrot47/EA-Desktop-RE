#!/usr/bin/env python3
"""Compatibility launcher for the installed EA Desktop client.

The program deliberately delegates authentication, entitlement checks, license
activation, elevation, anti-cheat setup, and process launch to EA's signed
EALauncher.exe. It does not read or copy EA credentials.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from urllib.parse import urlencode

if os.name == "nt":
    import winreg
else:  # pragma: no cover - the target application is Windows-only.
    winreg = None


EA_DESKTOP_KEY = r"SOFTWARE\Electronic Arts\EA Desktop"
DEFAULT_EA_LAUNCHER = Path(
    r"C:\Program Files\Electronic Arts\EA Desktop\EA Desktop\EALauncher.exe"
)
DEFAULT_EA_DESKTOP = Path(
    r"C:\Program Files\Electronic Arts\EA Desktop\EA Desktop\EADesktop.exe"
)
EA_LOG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Electronic Arts" / "EA Desktop" / "Logs"
DEFAULT_LIBRARY_CONFIG = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "EA Custom Launcher"
    / "library.json"
)

LAUNCH_RE = re.compile(
    r"Issuing launch: workingDirectory\[(?P<path>[^]]*)\] "
    r"offer\[(?P<offer>[^]]+)\] content\[(?P<content>[^]]*)\]",
    re.IGNORECASE,
)
TIMESTAMP_RE = re.compile(r"\[(?P<timestamp>\d{4}-\d{2}-\d{2}T[^]]+Z)\]")
EXIT_CODE_RE = re.compile(r"Game process exit code=\[(?P<code>-?\d+)\]", re.IGNORECASE)


@dataclass(frozen=True)
class InstalledGame:
    name: str
    install_location: str
    version: str | None = None
    publisher: str | None = None
    offer_id: str | None = None
    content_id: str | None = None
    source: str = "uninstall-registry"
    launch_context: str | None = None
    launch_id: str | None = None
    cmd_params: str | None = None


@dataclass(frozen=True)
class LaunchActivity:
    offer_id: str
    state: str
    requested_at: str | None = None
    updated_at: str | None = None
    exit_code: int | None = None


def _read_registry_value(root: int, path: str, name: str, view: int = 0) -> str | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value) if value is not None else None
    except OSError:
        return None


def resolve_ea_launcher() -> Path:
    if winreg is not None:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                value = _read_registry_value(root, EA_DESKTOP_KEY, "LauncherAppPath", view)
                if value and Path(value).is_file():
                    return Path(value)
    return DEFAULT_EA_LAUNCHER


def resolve_ea_desktop() -> Path:
    if winreg is not None:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                value = _read_registry_value(root, EA_DESKTOP_KEY, "DesktopAppPath", view)
                if value and Path(value).is_file():
                    return Path(value)
    return DEFAULT_EA_DESKTOP


def _registry_views():
    if winreg is None:
        return
    paths = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    seen: set[tuple[int, str]] = set()
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for path in paths:
            key = (root, path)
            if key not in seen:
                seen.add(key)
                yield root, path


def _enum_uninstall_entries() -> list[dict[str, str]]:
    if winreg is None:
        return []
    entries: list[dict[str, str]] = []
    for root, path in _registry_views():
        try:
            with winreg.OpenKey(root, path) as parent:
                count = winreg.QueryInfoKey(parent)[0]
                for index in range(count):
                    try:
                        child_name = winreg.EnumKey(parent, index)
                        with winreg.OpenKey(parent, child_name) as child:
                            item: dict[str, str] = {}
                            for field in ("DisplayName", "DisplayVersion", "Publisher", "InstallLocation"):
                                try:
                                    value, _ = winreg.QueryValueEx(child, field)
                                    if value:
                                        item[field] = str(value)
                                except OSError:
                                    pass
                            if item:
                                entries.append(item)
                    except OSError:
                        continue
        except OSError:
            continue
    return entries


def _normal_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value.strip().rstrip("\\/")))


def recent_launches(log_dir: Path = EA_LOG_DIR) -> dict[str, tuple[str, str]]:
    """Map normalized working directories to the latest observed offer/content IDs."""
    result: dict[str, tuple[str, str]] = {}
    if not log_dir.is_dir():
        return result
    logs = sorted(log_dir.glob("EADesktop*.log"), key=lambda item: item.stat().st_mtime)
    for path in logs:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    match = LAUNCH_RE.search(line)
                    if match and match.group("path"):
                        result[_normal_path(match.group("path"))] = (
                            match.group("offer"),
                            match.group("content"),
                        )
        except OSError:
            continue
    return result


def launch_activity(offer_id: str, log_dir: Path = EA_LOG_DIR) -> LaunchActivity:
    """Infer the latest safe launch state from standard EA Desktop log markers.

    Only fixed state markers and the offer/exit code are returned. Raw log lines,
    URLs, account IDs, and authorization material are never exposed.
    """
    if not log_dir.is_dir():
        return LaunchActivity(offer_id=offer_id, state="no-log-data")
    events: list[tuple[str, int, str]] = []
    sequence = 0
    for path in log_dir.glob("EADesktop*.log"):
        if "verbose" in path.name.casefold():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if not any(
                        marker in line
                        for marker in (
                            "Issuing launch:",
                            "Successful launch. IDs:",
                            "Cloud Sync entry point pre game launch",
                            "Cloud sync completed successfully",
                            "Game process terminated",
                            "Game process exit code=[",
                            "Post game cloud sync completed successfully",
                        )
                    ):
                        continue
                    stamp = TIMESTAMP_RE.search(line)
                    if stamp:
                        events.append((stamp.group("timestamp"), sequence, line))
                        sequence += 1
        except OSError:
            continue
    events.sort(key=lambda item: (item[0], item[1]))

    latest: LaunchActivity | None = None
    active_offer: str | None = None
    for timestamp, _sequence, line in events:
        launch = LAUNCH_RE.search(line)
        if launch:
            active_offer = launch.group("offer")
            if active_offer.casefold() == offer_id.casefold():
                latest = LaunchActivity(offer_id=offer_id, state="requested", requested_at=timestamp, updated_at=timestamp)
            continue
        if latest is None or active_offer is None or active_offer.casefold() != offer_id.casefold():
            continue
        state = latest.state
        exit_code = latest.exit_code
        if "Successful launch. IDs:" in line:
            state = "accepted"
        elif "Cloud Sync entry point pre game launch" in line:
            state = "pre-launch-cloud-sync"
        elif "Cloud sync completed successfully" in line:
            state = "running-or-starting"
        elif "Game process terminated" in line:
            state = "terminated"
        elif "Game process exit code=[" in line:
            match = EXIT_CODE_RE.search(line)
            if match:
                exit_code = int(match.group("code"))
            state = "terminated"
        elif "Post game cloud sync completed successfully" in line:
            state = "complete"
        latest = replace(latest, state=state, updated_at=timestamp, exit_code=exit_code)
    return latest or LaunchActivity(offer_id=offer_id, state="never-observed")


def discover_installed_games() -> list[InstalledGame]:
    launches = recent_launches()
    games: list[InstalledGame] = []
    seen: set[tuple[str, str]] = set()
    for item in _enum_uninstall_entries():
        name = item.get("DisplayName", "").strip()
        publisher = item.get("Publisher", "").strip()
        location = item.get("InstallLocation", "").strip()
        if not name or not location:
            continue
        normalized = _normal_path(location)
        has_ea_publisher = "electronic arts" in publisher.lower()
        has_ea_launch_record = normalized in launches or any(
            _is_parent_path(normalized, working_dir) for working_dir in launches
        )
        if not has_ea_publisher and not has_ea_launch_record:
            continue
        if name.casefold() in {"ea app", "origin"}:
            continue
        identity = (name.casefold(), normalized)
        if identity in seen:
            continue
        seen.add(identity)
        offer_id = content_id = None
        if normalized in launches:
            offer_id, content_id = launches[normalized]
        else:
            # A launch may use a child working directory of the registered root.
            for working_dir, identifiers in launches.items():
                if _is_parent_path(normalized, working_dir):
                    offer_id, content_id = identifiers
                    break
        games.append(
            InstalledGame(
                name=name,
                install_location=location,
                version=item.get("DisplayVersion"),
                publisher=publisher,
                offer_id=offer_id,
                content_id=content_id,
            )
        )
    return sorted(games, key=lambda game: game.name.casefold())


def load_library_config(path: Path = DEFAULT_LIBRARY_CONFIG) -> list[dict[str, str]]:
    """Read user-maintained launch mappings without touching EA account data."""
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("games"), list):
        raise ValueError(f"unsupported launcher library format: {path}")
    result: list[dict[str, str]] = []
    for raw in data["games"]:
        if not isinstance(raw, dict):
            continue
        item = {str(key): str(value) for key, value in raw.items() if value is not None}
        context = item.get("context", "").upper()
        if context and context not in {"OFFER", "MASTERTITLE", "SLUG"}:
            raise ValueError(f"invalid launch context {context!r} in {path}")
        if item.get("name") or item.get("install_location"):
            item["context"] = context or "OFFER"
            result.append(item)
    return result


def save_library_mapping(
    *,
    name: str,
    install_location: str,
    identifier: str,
    context: str,
    cmd_params: str | None = None,
    path: Path = DEFAULT_LIBRARY_CONFIG,
) -> None:
    context = context.upper()
    if context not in {"OFFER", "MASTERTITLE", "SLUG"}:
        raise ValueError(f"unsupported context: {context}")
    games = load_library_config(path)
    normalized = _normal_path(install_location) if install_location else ""
    replacement = {
        "name": name,
        "install_location": install_location,
        "context": context,
        "id": identifier,
    }
    if cmd_params:
        replacement["cmd_params"] = cmd_params
    for index, item in enumerate(games):
        same_path = normalized and _normal_path(item.get("install_location", "")) == normalized
        same_name = item.get("name", "").casefold() == name.casefold()
        if same_path or same_name:
            games[index] = replacement
            break
    else:
        games.append(replacement)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": 1, "games": sorted(games, key=lambda item: item.get("name", "").casefold())}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def library_games(config_path: Path = DEFAULT_LIBRARY_CONFIG) -> list[InstalledGame]:
    """Overlay stable user mappings on discovered local installations."""
    discovered = discover_installed_games()
    configured = load_library_config(config_path)
    consumed: set[int] = set()
    result: list[InstalledGame] = []
    for game in discovered:
        normalized = _normal_path(game.install_location)
        match_index = next(
            (
                index
                for index, item in enumerate(configured)
                if _normal_path(item.get("install_location", "")) == normalized
                or item.get("name", "").casefold() == game.name.casefold()
            ),
            None,
        )
        if match_index is None:
            result.append(
                replace(
                    game,
                    launch_context="OFFER" if game.offer_id else None,
                    launch_id=game.offer_id,
                )
            )
            continue
        consumed.add(match_index)
        item = configured[match_index]
        result.append(
            replace(
                game,
                launch_context=item.get("context", "OFFER"),
                launch_id=item.get("id") or game.offer_id,
                cmd_params=item.get("cmd_params"),
                source=f"{game.source}+user-config",
            )
        )
    for index, item in enumerate(configured):
        if index in consumed:
            continue
        result.append(
            InstalledGame(
                name=item.get("name", "Unnamed game"),
                install_location=item.get("install_location", ""),
                launch_context=item.get("context", "OFFER"),
                launch_id=item.get("id"),
                cmd_params=item.get("cmd_params"),
                source="user-config",
            )
        )
    return sorted(result, key=lambda game: game.name.casefold())


def find_library_game(name: str, config_path: Path = DEFAULT_LIBRARY_CONFIG) -> InstalledGame:
    matches = [game for game in library_games(config_path) if game.name.casefold() == name.casefold()]
    if not matches:
        raise LookupError(f"game not found in launcher library: {name}")
    if len(matches) > 1:
        raise LookupError(f"game name is ambiguous: {name}")
    return matches[0]


def _is_parent_path(parent: str, child: str) -> bool:
    try:
        return os.path.commonpath((parent, child)) == parent
    except ValueError:
        return False


def build_origin2_uri(
    command: str,
    *,
    identifier: str | None = None,
    context_type: str = "OFFER",
    cmd_params: str | None = None,
    tracking_id: str | None = None,
    client_page: str | None = None,
) -> str:
    allowed_commands = {"game/launch", "library/open", "store/open", "store/checkout"}
    allowed_contexts = {"OFFER", "MASTERTITLE", "PAGE", "SLUG"}
    if command not in allowed_commands:
        raise ValueError(f"unsupported origin2 command: {command}")
    context_type = context_type.upper()
    if context_type not in allowed_contexts:
        raise ValueError(f"unsupported context type: {context_type}")
    if command == "game/launch" and not identifier:
        raise ValueError("game/launch requires an identifier")

    query: list[tuple[str, str]] = []
    if identifier:
        query.extend((('contextType', context_type), ('id', identifier)))
    if cmd_params:
        query.append(("cmdParams", cmd_params))
    if tracking_id:
        query.append(("trackingId", tracking_id))
    if client_page:
        query.append(("clientPage", client_page))
    encoded = urlencode(query)
    return f"origin2://{command}" + (f"?{encoded}" if encoded else "")


def ensure_ea_broker(timeout: float = 45.0) -> bool:
    """Start EA Desktop through its supported silent bootstrap if necessary."""
    if _process_running("EADesktop.exe"):
        return False
    launcher = resolve_ea_launcher()
    if not launcher.is_file():
        raise FileNotFoundError(f"EA launcher not found: {launcher}")
    subprocess.Popen([str(launcher), "-silent"], close_fds=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _process_running("EADesktop.exe"):
            return True
        time.sleep(0.25)
    raise TimeoutError("EA Desktop did not enter silent broker mode before the timeout")


def execute_uri(uri: str, *, cold_start: bool = True) -> int:
    launcher = resolve_ea_launcher()
    if not launcher.is_file():
        raise FileNotFoundError(f"EA launcher not found: {launcher}")
    if cold_start:
        ensure_ea_broker()
    subprocess.Popen([str(launcher), uri], close_fds=True)
    return 0


def _process_running(image_name: str) -> bool:
    if os.name != "nt":
        return False
    completed = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    rows = list(csv.reader(io.StringIO(completed.stdout)))
    return any(row and row[0].casefold() == image_name.casefold() for row in rows)


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return True
    except OSError:
        return False


def status() -> dict[str, object]:
    launcher = resolve_ea_launcher()
    return {
        "launcher_path": str(launcher),
        "launcher_exists": launcher.is_file(),
        "desktop_path": str(resolve_ea_desktop()),
        "cold_start_mode": "EALauncher.exe -silent",
        "processes": {
            name: _process_running(name)
            for name in ("EADesktop.exe", "EABackgroundService.exe", "EALocalHostSvc.exe")
        },
        "fixed_local_ports": {
            "local_host_service_3215": _port_open(3215),
            "game_sdk_3216": _port_open(3216),
            "game_sdk_alt_3217": _port_open(3217),
        },
    }


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="show EA component and local-port status")
    activity_parser = commands.add_parser("activity", help="show passive launch state from safe log markers")
    activity_parser.add_argument("--offer", required=True)
    discover_parser = commands.add_parser(
        "discover", help="discover registered EA games and correlate recent offer IDs"
    )
    discover_parser.add_argument("--config", type=Path, default=DEFAULT_LIBRARY_CONFIG)

    configure_parser = commands.add_parser("configure", help="save a local game-to-EA-ID mapping")
    configure_parser.add_argument("--name", required=True)
    configure_parser.add_argument("--path", required=True, dest="install_location")
    configured_identity = configure_parser.add_mutually_exclusive_group(required=True)
    configured_identity.add_argument("--offer")
    configured_identity.add_argument("--slug")
    configured_identity.add_argument("--master-title")
    configure_parser.add_argument("--cmd-params")
    configure_parser.add_argument("--config", type=Path, default=DEFAULT_LIBRARY_CONFIG)

    uri_parser = commands.add_parser("uri", help="build an origin2 URI")
    uri_parser.add_argument("action", choices=("game/launch", "library/open", "store/open", "store/checkout"))
    uri_parser.add_argument("--id", dest="identifier")
    uri_parser.add_argument("--context", default="OFFER", choices=("OFFER", "MASTERTITLE", "PAGE", "SLUG"))
    uri_parser.add_argument("--cmd-params")
    uri_parser.add_argument("--tracking-id")
    uri_parser.add_argument("--client-page")
    uri_parser.add_argument("--execute", action="store_true")
    uri_parser.add_argument("--no-cold-start", action="store_true")

    launch_parser = commands.add_parser("launch", help="launch through EA's entitlement/license broker")
    identity = launch_parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--offer")
    identity.add_argument("--slug")
    identity.add_argument("--master-title")
    identity.add_argument("--name", help="configured/discovered display name")
    launch_parser.add_argument("--cmd-params")
    launch_parser.add_argument("--config", type=Path, default=DEFAULT_LIBRARY_CONFIG)
    launch_parser.add_argument("--execute", action="store_true")
    launch_parser.add_argument("--no-cold-start", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "status":
        _print_json(status())
        return 0
    if args.command == "activity":
        _print_json(asdict(launch_activity(args.offer)))
        return 0
    if args.command == "discover":
        _print_json([asdict(game) for game in library_games(args.config)])
        return 0
    if args.command == "configure":
        if args.offer:
            identifier, context = args.offer, "OFFER"
        elif args.slug:
            identifier, context = args.slug, "SLUG"
        else:
            identifier, context = args.master_title, "MASTERTITLE"
        save_library_mapping(
            name=args.name,
            install_location=args.install_location,
            identifier=identifier,
            context=context,
            cmd_params=args.cmd_params,
            path=args.config,
        )
        print(args.config)
        return 0
    if args.command == "uri":
        uri = build_origin2_uri(
            args.action,
            identifier=args.identifier,
            context_type=args.context,
            cmd_params=args.cmd_params,
            tracking_id=args.tracking_id,
            client_page=args.client_page,
        )
        print(uri)
        return execute_uri(uri, cold_start=not args.no_cold_start) if args.execute else 0
    if args.command == "launch":
        if args.offer:
            identifier, context = args.offer, "OFFER"
        elif args.slug:
            identifier, context = args.slug, "SLUG"
        elif args.master_title:
            identifier, context = args.master_title, "MASTERTITLE"
        else:
            game = find_library_game(args.name, args.config)
            if not game.launch_id or not game.launch_context:
                raise LookupError(f"game has no offer, slug, or master-title mapping: {game.name}")
            identifier, context = game.launch_id, game.launch_context
            if args.cmd_params is None:
                args.cmd_params = game.cmd_params
        uri = build_origin2_uri(
            "game/launch", identifier=identifier, context_type=context, cmd_params=args.cmd_params
        )
        print(uri)
        return execute_uri(uri, cold_start=not args.no_cold_start) if args.execute else 0
    return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
