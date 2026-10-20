"""Prototype BFN supervisor: reuse the tested host and Desktop-named helper.

This process outlives the GUI/CLI. It never stops the game on caller exit, never
changes the EA installation/registry, and cleans up only its own support
processes after the game ends. No fixed gameplay duration is imposed.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time
import json

import frida

from .launch import launch_executable, resolve_installed_launcher
from .license import license_path, owned_content_id
from .library import load_snapshot_dpapi
from .managed_launch import BFN_CONTENT_ID, ROOT
from .console_trace import finish_console_trace, start_trace_forwarder
from tools.process_name_probe import probe_path, running_name_probe, stop_owned_probe
from tools.test_bfn_direct_lsx import GAME, DESKTOP, listening, process_map, wait_for_host


class SessionError(RuntimeError):
    pass


class StartupReporter:
    def __init__(self):
        self.sent = False

    def send(self, ok: bool, message: str = "") -> None:
        print(json.dumps({"ok": ok, "message": message}), flush=True)
        self.sent = True


class GameWatch:
    """Allow transient EAAC checks and a short final process-exit grace period."""
    def __init__(self, started: float):
        self.started = started
        self.last_busy = started
        self.seen_game = False

    def finished(self, active: bool, launcher_running: bool, now: float) -> bool:
        self.seen_game |= active
        if active or launcher_running:
            self.last_busy = now
            return False
        return now - self.last_busy >= 5


def _validate_start(device, location: Path, uid: str | None, locale: str):
    existing = process_map(device)
    if any(name in (GAME, DESKTOP, "EAAntiCheat.GameServiceLauncher.exe") for name in existing.values()):
        raise SessionError("BFN or EA Desktop is already running. Close it before starting another standalone session.")
    if any(listening(port) for port in (3216, 3217)):
        raise SessionError("LSX ports 3216/3217 are occupied. Close the existing EA client or LSX host first.")
    if not probe_path("desktop").is_file():
        raise SessionError("BFN compatibility helper is missing. Build it using tools/process_name_probe/README.md.")
    launcher = resolve_installed_launcher(location, launcher_uid=uid, locale=locale)
    if launcher.content_id != BFN_CONTENT_ID or launcher.executable.name != "EAAntiCheat.GameServiceLauncher.exe":
        raise SessionError("BFN managed launch requires its installed DiP anti-cheat launcher.")
    if not license_path(BFN_CONTENT_ID).is_file():
        raise SessionError("BFN's signed license is missing. Use Renew license before launching.")
    return launcher


def _check_account() -> None:
    try:
        snapshot = load_snapshot_dpapi(ROOT / "private" / "ea_library.dpapi")
        content_id = owned_content_id(snapshot, "Origin.OFR.50.0004873")
    except Exception:
        raise SessionError("BFN requires the signed-in standalone library and an active entitlement. Sign in and refresh the library.") from None
    if content_id != BFN_CONTENT_ID:
        raise SessionError("The standalone library does not identify the expected BFN content.")


def _start_host(*, trace: bool = False) -> subprocess.Popen:
    command = [sys.executable, "tools/probe_lsx_connection.py", "--seconds", "0", "--exclusive",
               "--send-challenge", "--ack-challenge", "--answer-startup", "--disable-overlay", "--answer-session"]
    if trace:
        command.append("--trace")
    host = subprocess.Popen(
        command, cwd=ROOT, stdout=subprocess.PIPE if trace else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if trace:
        host._ea_trace_thread = start_trace_forwarder(host.stdout, sys.stderr)
    return host


def _wait_for_support(host: subprocess.Popen) -> None:
    try:
        wait_for_host(host)
    except RuntimeError:
        raise SessionError("BFN's LSX host could not start. Check standalone sign-in and free ports 3216/3217.") from None


def _watch_game(device, host, game_launcher, helper_pid: int) -> int:
    watch = GameWatch(time.monotonic())
    while True:
        current = process_map(device)
        if host.poll() is not None or current.get(helper_pid) != DESKTOP:
            raise SessionError("BFN support process stopped unexpectedly; the game was not forcibly closed.")
        now = time.monotonic()
        active = GAME in current.values()
        if watch.finished(active, game_launcher.poll() is None, now):
            if not watch.seen_game:
                raise SessionError("The anti-cheat launcher exited without starting BFN.")
            return game_launcher.returncode or 0
        if not watch.seen_game and now - watch.started > 120:
            # Abort only the owned startup launcher, never an existing game.
            stop_owned_probe(game_launcher)
            raise SessionError("BFN did not appear within the startup window.")
        time.sleep(0.5)


def run_session(location: Path, uid: str | None, locale: str, reporter: StartupReporter, *, trace: bool = False) -> int:
    device = frida.get_local_device()
    launcher = _validate_start(device, location, uid, locale)
    _check_account()
    host = _start_host(trace=True) if trace else _start_host()
    try:
        _wait_for_support(host)
        with running_name_probe("desktop", device, {}) as helper_pid:
            reporter.send(True)
            # The parent authorizes launch only after receiving readiness. EOF
            # before that cancels startup and releases the host/helper.
            if sys.stdin.readline().strip() != "launch":
                return 0
            game_launcher = launch_executable(
                launcher.executable, launcher.arguments,
                working_directory=location, content_id=launcher.content_id,
            )
            return _watch_game(device, host, game_launcher, helper_pid)
    finally:
        stop_owned_probe(host)
        finish_console_trace(host)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("location", type=Path)
    parser.add_argument("--launcher-uid")
    parser.add_argument("--locale", default="en_US")
    parser.add_argument("--trace", action="store_true", help="forward redacted LSX/HTTP traces on the separate console channel")
    args = parser.parse_args()
    reporter = StartupReporter()
    try:
        return run_session(args.location, args.launcher_uid, args.locale, reporter, trace=args.trace)
    except Exception as exc:
        if not reporter.sent:
            # Never serialize raw protocol/network exceptions or credentials.
            message = str(exc) if isinstance(exc, SessionError) else "BFN session startup failed; check its installation and helper build."
            try:
                reporter.send(False, message)
            except BrokenPipeError:
                pass  # Caller already cancelled startup; owned cleanup ran.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
