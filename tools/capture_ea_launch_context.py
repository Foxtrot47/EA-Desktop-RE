#!/usr/bin/env python3
"""Capture redacted EA Desktop process creation context for BFN."""

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
from tools.frida_redirect_ea_lsx import HOOK as REDIRECT_LSX_HOOK


DESKTOP = Path(r"C:\Program Files\Electronic Arts\EA Desktop\EA Desktop\EADesktop.exe")
LAUNCHER = DESKTOP.with_name("EALauncher.exe")
URI = "origin2://game/launch?offerIds=194814"
HOOK = r"""
function decodeEnvironment(address, flags) {
    if (address.isNull()) return {kind: 'inherited', entries: []};
    const unicode = (flags & 0x400) !== 0;
    const names = [];
    let offset = 0;
    const limit = 131072;
    while (offset < limit) {
        let value;
        if (unicode) {
            value = address.add(offset).readUtf16String();
            offset += (value.length + 1) * 2;
        } else {
            value = address.add(offset).readCString();
            offset += value.length + 1;
        }
        if (value.length === 0) break;
        const separator = value.indexOf('=');
        if (separator > 0) {
            const name = value.slice(0, separator);
            if (name.startsWith('EA') || ['ContentId', 'OriginSessionKey', 'SteamAppId', 'IGOCacheDirPath', 'IGOLogDirPath'].includes(name)) {
                names.push({name: name, value: value.slice(separator + 1)});
            }
        }
    }
    return {kind: unicode ? 'unicode' : 'ansi', entries: names};
}
function basename(path) { return path.split(/[\\/]/).pop(); }
function hook(moduleName, name, appIndex, commandIndex, flagsIndex, envIndex) {
    const module = Process.findModuleByName(moduleName);
    if (module === null) return false;
    const target = module.getExportByName(name);
    Interceptor.attach(target, {
        onEnter(args) {
            try {
                const app = args[appIndex].isNull() ? '' : args[appIndex].readUtf16String();
                const command = args[commandIndex].isNull() ? '' : args[commandIndex].readUtf16String();
                const combined = app + ' ' + command;
                if (!/EAAntiCheat\.GameServiceLauncher|PVZBattleforNeighborville/i.test(combined)) return;
                const flags = args[flagsIndex].toUInt32();
                send({
                    event: name,
                    executable: basename(app),
                    commandLength: command.length,
                    flags: flags,
                    environment: decodeEnvironment(args[envIndex], flags)
                });
            } catch (error) { send({event: 'capture_error', detail: String(error)}); }
        }
    });
    return true;
}
hook('kernel32.dll', 'CreateProcessW', 0, 1, 5, 6);
hook('advapi32.dll', 'CreateProcessAsUserW', 1, 2, 6, 7);
send({event: 'hooks_ready'});
"""


def _listening(port: int = 3216) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=80)
    parser.add_argument("--pid", type=int, help="attach to an existing EA Desktop process")
    parser.add_argument("--replay", action="store_true", help="test a direct launch using EA's captured environment in memory")
    parser.add_argument("--offline-replay", action="store_true", help="replay the captured environment with only the independent LSX host")
    parser.add_argument("--coexist-redirected-desktop", action="store_true", help="diagnostic: keep EA Desktop running on redirected LSX ports while BFN uses the independent host")
    parser.add_argument("--output", type=Path, default=Path("analysis/runtime/bfn_normal_launch_context.json"))
    args = parser.parse_args()
    if args.coexist_redirected_desktop and not args.offline_replay:
        parser.error("--coexist-redirected-desktop requires --offline-replay")
    device = frida.get_local_device()
    if args.pid is None and any(p.name == "EADesktop.exe" for p in device.enumerate_processes()):
        raise SystemExit("Close EA Desktop before spawn capture, or pass --pid")
    events: list[dict] = []
    captured_environment: dict[str, str] = {}
    pid = args.pid if args.pid is not None else device.spawn([str(DESKTOP)])
    session = None
    host: subprocess.Popen[str] | None = None
    host_log = None
    game_pids: set[int] = set()
    replay_desktop_pids: set[int] = set()
    redirected_desktop_pid: int | None = None
    redirected_desktop_session = None
    try:
        session = device.attach(pid)
        script = session.create_script(HOOK)

        def on_message(message: dict, data: bytes | None) -> None:
            payload = message.get("payload")
            if isinstance(payload, dict):
                if "environment" in payload:
                    entries = payload["environment"]["entries"]
                    captured_environment.update({item["name"]: item["value"] for item in entries})
                    payload["environment"]["entries"] = [
                        {"name": item["name"], "valueLength": len(item["value"])} for item in entries
                    ]
                events.append(payload)
                print({
                    "event": payload["event"], "executable": payload.get("executable"),
                    "environment_kind": payload.get("environment", {}).get("kind"),
                    "environment_names": [item["name"] for item in payload.get("environment", {}).get("entries", [])],
                }, flush=True)
            else:
                print(message.get("description", "Frida message"), flush=True)

        script.on("message", on_message)
        script.load()
        if args.pid is None:
            device.resume(pid)
        for _ in range(150):
            if _listening():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("EA Desktop LSX did not start")
        print("EA Desktop LSX ready; requesting normal BFN launch", flush=True)
        subprocess.Popen([str(LAUNCHER), URI], cwd=str(DESKTOP.parent))
        deadline = time.monotonic() + args.seconds
        ever_game = False
        while time.monotonic() < deadline:
            current = {p.pid for p in device.enumerate_processes() if p.name == "PVZBattleforNeighborville.exe"}
            game_pids |= current
            if current and not ever_game:
                print("BFN process started", flush=True)
                ever_game = True
                if args.replay or args.offline_replay:
                    time.sleep(20)
                    subprocess.run([
                        "powershell", "-NoProfile", "-Command",
                        "Get-Process PVZBattleforNeighborville -ErrorAction SilentlyContinue | ForEach-Object { $_.CloseMainWindow() | Out-Null }",
                    ], check=False, capture_output=True)
                    for _ in range(30):
                        if not any(p.name == "PVZBattleforNeighborville.exe" for p in device.enumerate_processes()):
                            break
                        time.sleep(0.5)
                    launcher = resolve_installed_launcher(r"E:\Games\Plants vs Zombies Battle for Neighborville")
                    environment = build_launch_environment(content_id=launcher.content_id)
                    environment.update(captured_environment)
                    if args.offline_replay:
                        for desktop in device.enumerate_processes():
                            if desktop.name == "EADesktop.exe":
                                try:
                                    device.kill(desktop.pid)
                                except frida.InvalidOperationError:
                                    pass
                        for _ in range(20):
                            if not _listening():
                                break
                            time.sleep(0.25)
                        host_path = Path("analysis/runtime/bfn_offline_replay_host.log")
                        host_path.parent.mkdir(parents=True, exist_ok=True)
                        host_log = host_path.open("w", encoding="utf-8")
                        host = subprocess.Popen(
                            [sys.executable, "tools/probe_lsx_connection.py", "--seconds", "80",
                             "--send-challenge", "--ack-challenge", "--answer-startup"],
                            cwd=str(Path(__file__).resolve().parents[1]),
                            stdout=host_log, stderr=subprocess.STDOUT, text=True,
                        )
                        for _ in range(40):
                            if _listening():
                                break
                            time.sleep(0.1)
                        else:
                            raise RuntimeError("independent LSX host did not bind")
                        print("EA Desktop stopped; independent LSX host ready (readiness check opens one short LSX connection)", flush=True)
                        if args.coexist_redirected_desktop:
                            redirected_desktop_pid = device.spawn([str(DESKTOP)])
                            redirected_desktop_session = device.attach(redirected_desktop_pid)
                            redirect_script = redirected_desktop_session.create_script(REDIRECT_LSX_HOOK)
                            redirect_script.on("message", lambda message, data: print(
                                {"desktop_redirect": message.get("payload") or message.get("description")},
                                flush=True,
                            ))
                            redirect_script.load()
                            device.resume(redirected_desktop_pid)
                            for _ in range(100):
                                if _listening(13216):
                                    break
                                time.sleep(0.1)
                            else:
                                raise RuntimeError("redirected EA Desktop LSX did not bind port 13216")
                            print(f"diagnostic EA Desktop pid={redirected_desktop_pid} uses redirected LSX; BFN still sees standalone host", flush=True)
                    replay = subprocess.Popen(
                        [str(launcher.executable), *launcher.arguments],
                        cwd=str(launcher.executable.parent), env=environment,
                    )
                    print(f"replayed direct anti-cheat launch pid={replay.pid} with captured EA fields", flush=True)
                    replay_seen = False
                    for _ in range(100):
                        processes = device.enumerate_processes()
                        active = any(p.name == "PVZBattleforNeighborville.exe" for p in processes)
                        if args.offline_replay:
                            if host is not None and host.poll() is not None:
                                print(f"independent LSX host exited with code {host.returncode}", flush=True)
                                break
                            for desktop in processes:
                                if (desktop.name != "EADesktop.exe" or desktop.pid in replay_desktop_pids
                                        or desktop.pid == redirected_desktop_pid):
                                    continue
                                replay_desktop_pids.add(desktop.pid)
                                print(f"BFN auto-started EA Desktop pid={desktop.pid}; stopping test child", flush=True)
                                try:
                                    device.kill(desktop.pid)
                                except frida.InvalidOperationError:
                                    pass
                        if active and not replay_seen:
                            print("replay BFN process started", flush=True)
                            replay_seen = True
                        if replay_seen and not active:
                            print("replay BFN process exited", flush=True)
                            break
                        time.sleep(0.5)
                    if replay_seen and active:
                        print("replay BFN survived 50 seconds", flush=True)
                    subprocess.run([
                        "powershell", "-NoProfile", "-Command",
                        "Get-Process PVZBattleforNeighborville -ErrorAction SilentlyContinue | ForEach-Object { $_.CloseMainWindow() | Out-Null }",
                    ], check=False, capture_output=True)
                    break
            if ever_game and not current:
                print("BFN process exited", flush=True)
                break
            time.sleep(0.5)
    finally:
        if redirected_desktop_pid is not None:
            try:
                device.kill(redirected_desktop_pid)
            except frida.InvalidOperationError:
                pass
        if redirected_desktop_session is not None:
            try:
                redirected_desktop_session.detach()
            except frida.InvalidOperationError:
                pass
        if host is not None:
            host.terminate()
            try:
                host.wait(timeout=5)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait()
        if host_log is not None:
            host_log.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"schema": 1, "events": events}, indent=2), encoding="utf-8")
        print(f"saved {len(events)} redacted launch-context events", flush=True)
        if session is not None:
            try:
                session.detach()
            except frida.InvalidOperationError:
                pass
        # Leave the game and EA Desktop running if the launch succeeded: this
        # capture does not own the user's ongoing game session.


if __name__ == "__main__":
    main()
