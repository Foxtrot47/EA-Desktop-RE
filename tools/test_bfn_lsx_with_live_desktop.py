#!/usr/bin/env python3
"""Diagnostic: normal EA launch with BFN pointed at an independent LSX host.

EA Desktop remains running for launch coordination, but its LSX bind is
redirected to 13216/13217. BFN's 3216/3217 sockets belong to our host.
No game or installed binary is modified. This is not an EA-free launch.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

import frida

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.frida_redirect_ea_lsx import DESKTOP, HOOK


LAUNCHER = DESKTOP.with_name("EALauncher.exe")
URI = "origin2://game/launch?offerIds=194814"


def listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=45)
    args = parser.parse_args()
    device = frida.get_local_device()
    if any(p.name == "EADesktop.exe" for p in device.enumerate_processes()):
        raise SystemExit("Stop EA Desktop before this isolated diagnostic")
    if listening(3216) or listening(13216):
        raise SystemExit("LSX test ports are already occupied")

    log_path = Path("analysis/runtime/bfn_live_desktop_independent_lsx.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as host_log:
        host = subprocess.Popen(
            [sys.executable, "tools/probe_lsx_connection.py", "--seconds", str(args.seconds + 40),
             "--send-challenge", "--ack-challenge", "--answer-startup"],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdout=host_log, stderr=subprocess.STDOUT, text=True,
        )
        desktop_pid: int | None = None
        desktop_session = None
        launcher_process = None
        game_pids: set[int] = set()
        try:
            for _ in range(100):
                if listening(3216):
                    break
                if host.poll() is not None:
                    raise RuntimeError(f"independent LSX host exited: {host.returncode}")
                time.sleep(0.1)
            else:
                raise RuntimeError("independent LSX host did not bind")
            print("independent LSX host ready; first short connection is test readiness probe", flush=True)

            desktop_pid = device.spawn([str(DESKTOP)])
            desktop_session = device.attach(desktop_pid)
            script = desktop_session.create_script(HOOK)
            script.on("message", lambda message, data: print(
                {"desktop_redirect": message.get("payload") or message.get("description")},
                flush=True,
            ))
            script.load()
            device.resume(desktop_pid)
            for _ in range(150):
                if listening(13216):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("redirected EA Desktop LSX did not bind")
            print(f"EA Desktop pid={desktop_pid} bound 13216; starting BFN normally", flush=True)
            launcher_process = subprocess.Popen([str(LAUNCHER), URI], cwd=str(DESKTOP.parent))

            started = time.monotonic()
            ever_game = False
            while time.monotonic() - started < args.seconds:
                active = {p.pid for p in device.enumerate_processes() if p.name == "PVZBattleforNeighborville.exe"}
                game_pids |= active
                if active and not ever_game:
                    print(f"BFN started pids={sorted(active)}", flush=True)
                    ever_game = True
                if ever_game and not active:
                    print(f"BFN exited after {time.monotonic()-started:.1f}s", flush=True)
                    break
                time.sleep(0.5)
            else:
                print(f"BFN alive after {args.seconds}s={ever_game}", flush=True)
        finally:
            for pid in game_pids:
                try:
                    device.kill(pid)
                except frida.InvalidOperationError:
                    pass
            if desktop_pid is not None:
                try:
                    device.kill(desktop_pid)
                except frida.InvalidOperationError:
                    pass
            if desktop_session is not None:
                try:
                    desktop_session.detach()
                except frida.InvalidOperationError:
                    pass
            host.terminate()
            try:
                host.wait(timeout=5)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait()
            if launcher_process is not None and launcher_process.poll() is None:
                launcher_process.terminate()
            print(f"LSX host trace: {log_path}", flush=True)


if __name__ == "__main__":
    main()
