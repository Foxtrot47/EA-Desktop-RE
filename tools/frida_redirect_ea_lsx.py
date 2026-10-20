#!/usr/bin/env python3
"""Temporarily redirect EA Desktop's LSX bind ports for a local relay test.

This hooks only EADesktop.exe, not the anti-cheat protected game.  No binary,
registry, or installed file is modified.  The process spawned by this script
is terminated when the timed test ends.
"""

from __future__ import annotations

import argparse
import socket
import time
from pathlib import Path

import frida


DESKTOP = Path(r"C:\Program Files\Electronic Arts\EA Desktop\EA Desktop\EADesktop.exe")
HOOK = r"""
let installed = false;
function install() {
    if (installed) return true;
    const module = Process.findModuleByName('ws2_32.dll');
    if (module === null) return false;
    const target = module.getExportByName('bind');
    Interceptor.attach(target, {
        onEnter(args) {
            try {
                const address = args[1];
                const port = (address.add(2).readU8() << 8) | address.add(3).readU8();
                if (port === 3216 || port === 3217) {
                    const replacement = port + 10000;
                    address.add(2).writeU8((replacement >> 8) & 0xff);
                    address.add(3).writeU8(replacement & 0xff);
                    send({ event: 'redirected', from: port, to: replacement });
                }
            } catch (error) {
                send({ event: 'hook_error', detail: String(error) });
            }
        }
    });
    installed = true;
    send({ event: 'hook_ready' });
    return true;
}
if (!install()) {
    const timer = setInterval(function () { if (install()) clearInterval(timer); }, 10);
}
"""


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=20)
    args = parser.parse_args()
    if not DESKTOP.is_file():
        raise SystemExit(f"EA Desktop executable missing: {DESKTOP}")
    device = frida.get_local_device()
    existing = {p.pid for p in device.enumerate_processes() if p.name == "EADesktop.exe"}
    if existing:
        raise SystemExit("Close existing EA Desktop processes before redirect test")
    pid = device.spawn([str(DESKTOP)])
    session = None
    try:
        session = device.attach(pid)
        script = session.create_script(HOOK)
        script.on("message", lambda message, data: print(message.get("payload") or message.get("description"), flush=True))
        script.load()
        device.resume(pid)
        print(f"spawned EA Desktop pid={pid}", flush=True)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            if _listening(13216):
                print("redirected LSX port 13216 is listening", flush=True)
                break
            time.sleep(0.25)
        else:
            print("redirected LSX listener was not observed", flush=True)
    finally:
        if session is not None:
            session.detach()
        try:
            device.kill(pid)
        except frida.InvalidOperationError:
            pass


if __name__ == "__main__":
    main()
