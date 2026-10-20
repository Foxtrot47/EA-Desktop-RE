#!/usr/bin/env python3
"""Bounded direct BFN diagnostic; never attach to or patch the game/anti-cheat.

Requires permission to close test-started BFN/EA processes. EA Desktop children
are recorded and stopped, not hidden; their appearance falsifies continuous
EA Desktop absence even if the game survives.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import frida

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from standalone_launcher.launch import build_launch_environment, resolve_installed_launcher
from tools.process_name_probe import PROBE_NAMES, running_name_probe


ROOT = Path(__file__).resolve().parents[1]
INSTALL = Path(r"E:\Games\Plants vs Zombies Battle for Neighborville")
GAME = "PVZBattleforNeighborville.exe"
DESKTOP = "EADesktop.exe"
WATCHED = {
    GAME, DESKTOP, "EALauncher.exe", "EALaunchHelper.exe",
    "EAAntiCheat.GameServiceLauncher.exe", "EAAntiCheat.GameService.exe",
    "EABackgroundService.exe", "EACefSubProcess.exe", "EACrashReporter.exe",
}


def listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def process_map(device) -> dict[int, str]:
    return {p.pid: p.name for p in device.enumerate_processes() if p.name in WATCHED}


def stop_process(device, pid: int, events: list[dict], reason: str) -> None:
    try:
        device.kill(pid)
        events.append({"event": "stop_requested", "pid": pid, "reason": reason})
    except frida.ProcessNotFoundError:
        events.append({"event": "already_exited", "pid": pid})


def start_host(seconds: int, disable_overlay: bool, log, *, answer_session: bool = False) -> subprocess.Popen:
    command = [sys.executable, "tools/probe_lsx_connection.py", "--seconds", str(seconds + 20),
               "--send-challenge", "--ack-challenge", "--answer-startup"]
    if disable_overlay:
        command.append("--disable-overlay")
    if answer_session:
        command.append("--answer-session")
    return subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)


def wait_for_host(host: subprocess.Popen) -> None:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if host.poll() is not None:
            raise RuntimeError(f"LSX host exited with code {host.returncode}")
        if listening(3216):
            return
        time.sleep(0.1)
    raise RuntimeError("LSX host did not bind")


def record_changes(previous: dict[int, str], current: dict[int, str], elapsed: float, events: list[dict]) -> None:
    for pid in current.keys() - previous.keys():
        events.append({"event": "started", "pid": pid, "name": current[pid], "seconds": elapsed})
    for pid in previous.keys() - current.keys():
        events.append({"event": "exited", "pid": pid, "name": previous[pid], "seconds": elapsed})


def stop_new_desktops(device, current: dict[int, str], baseline: dict[int, str], stopped: set[int], events: list[dict], first_seen: dict[int, float], elapsed: float, grace: float) -> None:
    for pid in current.keys() - baseline.keys() - stopped:
        if current[pid] != DESKTOP:
            continue
        since = first_seen.setdefault(pid, elapsed)
        if elapsed - since >= grace:
            stop_process(device, pid, events, "auto_started_desktop")
            stopped.add(pid)


def observe(device, baseline: dict[int, str], host: subprocess.Popen, seconds: int, *, desktop_grace: float = 0) -> dict:
    started = time.monotonic()
    previous = baseline
    seen: dict[int, str] = {}
    stopped: set[int] = set()
    first_desktop_seen: dict[int, float] = {}
    events: list[dict] = []
    ever_game = False
    active_game = False
    try:
        while time.monotonic() - started < seconds:
            current = process_map(device)
            elapsed = round(time.monotonic() - started, 3)
            record_changes(previous, current, elapsed, events)
            seen.update({pid: name for pid, name in current.items() if pid not in baseline})
            previous = current
            active_game = GAME in current.values()
            ever_game |= active_game
            stop_new_desktops(device, current, baseline, stopped, events, first_desktop_seen, elapsed, desktop_grace)
            if host.poll() is not None:
                raise RuntimeError(f"LSX host exited with code {host.returncode}")
            # EAAC can create a short-lived game process before its real launch.
            # Observe the entire budget rather than terminating that launch early.
            time.sleep(0.1)
        return {
            "observation_seconds": round(time.monotonic() - started, 3),
            "game_seen": ever_game, "game_alive_at_end": active_game,
            "desktop_observed": DESKTOP in seen.values(),
            "menu_verified": False, "events": events,
        }
    finally:
        # Preflight excludes existing games/desktops. Preserve all baseline PIDs,
        # including an already-running shared background service.
        for pid in process_map(device).keys() - baseline.keys():
            stop_process(device, pid, events, "test_cleanup")


def preflight(device, *, name_probe: bool) -> dict[int, str]:
    baseline = process_map(device)
    if any(name != "EABackgroundService.exe" for name in baseline.values()):
        raise RuntimeError("Close BFN and EA Desktop/helpers before this isolated diagnostic")
    if name_probe and baseline:
        raise RuntimeError("Name-only comparisons require all real EA/BFN processes to be closed")
    if any(listening(port) for port in (3216, 3217)):
        raise RuntimeError("LSX test ports are occupied")
    return baseline


def run(args, result: dict) -> None:
    device = frida.get_local_device()
    baseline = preflight(device, name_probe=bool(args.name_probe))
    launcher = resolve_installed_launcher(INSTALL)
    environment = build_launch_environment(content_id=launcher.content_id)
    flags = subprocess.CREATE_BREAKAWAY_FROM_JOB if args.breakaway else 0
    result.update({"creation_flags": flags, "baseline_processes": list(baseline.values())})
    with args.output.with_suffix(".host.log").open("x", encoding="utf-8") as log:
        host = start_host(args.seconds, args.disable_overlay, log, answer_session=args.answer_session)
        try:
            wait_for_host(host)
            with running_name_probe(args.name_probe, device, result) as probe_pid:
                observation_baseline = dict(baseline)
                if probe_pid is not None:
                    # Preserve the explicitly labelled inert probe until this
                    # context closes it; it is not genuine EA software.
                    observation_baseline[probe_pid] = PROBE_NAMES[args.name_probe]
                with subprocess.Popen(
                    [str(launcher.executable), *launcher.arguments], cwd=INSTALL,
                    env=environment, creationflags=flags,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                ) as game_launcher:
                    try:
                        result.update(observe(device, observation_baseline, host, args.seconds, desktop_grace=args.desktop_grace))
                    finally:
                        # observe closes any still-running test-owned launcher.
                        if game_launcher.poll() is None:
                            game_launcher.terminate()
                    result["launcher_exit_code"] = game_launcher.wait(timeout=5)
        finally:
            host.terminate()
            try:
                host.wait(timeout=5)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--disable-overlay", action="store_true")
    parser.add_argument("--breakaway", action="store_true")
    parser.add_argument("--answer-session", action="store_true")
    parser.add_argument("--desktop-grace", type=float, default=0, help="diagnostic: delay stopping each new EA Desktop by 0-5 seconds")
    parser.add_argument("--name-probe", choices=tuple(PROBE_NAMES), help="explicitly labelled inert process-name comparison; requires built probe binaries")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 120:
        parser.error("--seconds must be between 1 and 120")
    if not 0 <= args.desktop_grace <= 5:
        parser.error("--desktop-grace must be between 0 and 5")
    if args.output.exists() or args.output.with_suffix(".host.log").exists():
        parser.error("output already exists; choose a new path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {"schema": 1, "mode": "fresh_direct_name_probe" if args.name_probe else "fresh_direct", "overlay_disabled": args.disable_overlay,
              "answer_session": args.answer_session, "desktop_grace_seconds": args.desktop_grace,
              "readiness_probe_opens_connection": True}
    try:
        run(args, result)
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        raise
    finally:
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
