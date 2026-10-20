#!/usr/bin/env python3
"""Temporary EA Desktop LSX relay for BFN startup comparison.

Frida changes only EA Desktop's bind() port in memory.  This relay forwards
the game's original LSX packets, optionally replacing selected SDK responses.
It records message names and mismatch field names, never payload values.
"""

from __future__ import annotations

import argparse
import json
import select
import socket
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import frida

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from standalone_launcher.launch import launch_installed_game
from standalone_launcher.library import load_snapshot_dpapi
from standalone_launcher.lsx_startup import startup_reply
from tools.frida_redirect_ea_lsx import DESKTOP, HOOK, _listening
from tools.probe_lsx_connection import _codec_key, _decrypt_packet, _encrypt_packet


class RelayConnection:
    def __init__(self, client: socket.socket, upstream: socket.socket, snapshot: dict, replace: set[str], events: list[dict], lock: threading.Lock):
        self.client = client
        self.upstream = upstream
        self.snapshot = snapshot
        self.replace = replace
        self.events = events
        self.lock = lock
        self.buffers = {client: b"", upstream: b""}
        self.codec_key: bytes | None = None
        self.pending: dict[str, ET.Element] = {}

    def _record(self, value: dict) -> None:
        with self.lock:
            self.events.append(value)
        print(f"LSX {value['direction']} {value['message']}" + (
            f" differences={value['differences']}" if value.get("differences") else ""
        ), flush=True)

    def _frame(self, source: socket.socket, packet: bytes) -> bytes:
        direction = "game" if source is self.client else "desktop"
        plain = packet if packet.startswith(b"<LSX>") else (
            _decrypt_packet(packet, self.codec_key) if self.codec_key else None
        )
        if plain is None:
            self._record({"direction": direction, "message": "opaque", "bytes": len(packet)})
            return packet + b"\0"
        try:
            root = ET.fromstring(plain)
            envelope = root[0]
            message = envelope[0]
        except (ET.ParseError, IndexError):
            self._record({"direction": direction, "message": "unparsed", "bytes": len(packet)})
            return packet + b"\0"
        record: dict = {"direction": direction, "message": message.tag, "fields": sorted(message.attrib)}
        if direction == "desktop" and message.tag == "ChallengeAccepted":
            response = message.attrib.get("response", "")
            if len(response) >= 2:
                self.codec_key = _codec_key(response)
        request_id = envelope.attrib.get("id", "")
        if direction == "game" and envelope.tag == "Request":
            self.pending[request_id] = envelope
            for field in ("SettingId", "GameInfoId"):
                value = message.attrib.get(field, "")
                if value.isascii() and value.replace("_", "").isupper() and len(value) <= 40:
                    record[field] = value
        if direction == "desktop" and envelope.tag == "Response":
            request = self.pending.pop(request_id, None)
            if request is not None:
                generated = startup_reply(request, self.snapshot)
                if generated is not None:
                    expected = ET.fromstring(generated)[0][0]
                    differences = sorted(
                        name for name in set(expected.attrib) | set(message.attrib)
                        if expected.attrib.get(name) != message.attrib.get(name)
                    )
                    if expected.tag != message.tag:
                        differences.insert(0, "response_tag")
                    if differences:
                        record["differences"] = differences
                    if message.tag in self.replace and self.codec_key:
                        record["replaced"] = True
                        self._record(record)
                        return _encrypt_packet(generated, self.codec_key)
        self._record(record)
        return packet + b"\0"

    def run(self) -> None:
        sockets = (self.client, self.upstream)
        try:
            while True:
                readable, _, _ = select.select(sockets, [], [], 0.5)
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    destination = self.upstream if source is self.client else self.client
                    self.buffers[source] += data
                    if len(self.buffers[source]) > 8 * 1024 * 1024:
                        raise RuntimeError("LSX frame exceeded 8 MiB")
                    while b"\0" in self.buffers[source]:
                        frame, self.buffers[source] = self.buffers[source].split(b"\0", 1)
                        destination.sendall(self._frame(source, frame))
        finally:
            self.client.close()
            self.upstream.close()


def _listen(port: int, stop: threading.Event, snapshot: dict, replace: set[str], events: list[dict], lock: threading.Lock) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen()
        listener.settimeout(0.5)
        print(f"relay listening {port}->{port + 10000}", flush=True)
        while not stop.is_set():
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            try:
                upstream = socket.create_connection(("127.0.0.1", port + 10000), timeout=5)
            except OSError:
                client.close()
                continue
            threading.Thread(
                target=RelayConnection(client, upstream, snapshot, replace, events, lock).run,
                daemon=True,
            ).start()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--replace", action="append", default=[], help="LSX response tag to replace with a standalone reply")
    parser.add_argument("--output", type=Path, default=Path("analysis/runtime/bfn_relay_comparison.json"))
    args = parser.parse_args()
    snapshot = load_snapshot_dpapi(Path("private/ea_library.dpapi"))
    device = frida.get_local_device()
    if any(p.name == "EADesktop.exe" for p in device.enumerate_processes()):
        raise SystemExit("Close EA Desktop before starting the relay")
    stop = threading.Event()
    events: list[dict] = []
    lock = threading.Lock()
    desktop_pid = device.spawn([str(DESKTOP)])
    session = None
    game_pids: set[int] = set()
    try:
        session = device.attach(desktop_pid)
        script = session.create_script(HOOK)
        script.on("message", lambda message, data: print("Frida", message.get("payload") or message.get("description"), flush=True))
        script.load()
        device.resume(desktop_pid)
        for _ in range(100):
            if _listening(13216):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("EA Desktop did not bind redirected LSX port")
        threads = [
            threading.Thread(target=_listen, args=(port, stop, snapshot, set(args.replace), events, lock), daemon=True)
            for port in (3216, 3217)
        ]
        for thread in threads:
            thread.start()
        time.sleep(0.5)
        launcher, process = launch_installed_game(r"E:\Games\Plants vs Zombies Battle for Neighborville")
        print(f"started {launcher.executable.name} pid={process.pid}", flush=True)
        ever_game = False
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            current = {p.pid for p in device.enumerate_processes() if p.name == "PVZBattleforNeighborville.exe"}
            game_pids |= current
            if current and not ever_game:
                print("BFN game process started", flush=True)
                ever_game = True
            if ever_game and not current:
                print("BFN game process exited", flush=True)
                break
            time.sleep(0.5)
    finally:
        stop.set()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"schema": 1, "events": events}, indent=2), encoding="utf-8")
        print(f"saved {len(events)} redacted relay events", flush=True)
        for pid in game_pids:
            try:
                device.kill(pid)
            except frida.InvalidOperationError:
                pass
        if session is not None:
            session.detach()
        try:
            device.kill(desktop_pid)
        except frida.InvalidOperationError:
            pass


if __name__ == "__main__":
    main()
