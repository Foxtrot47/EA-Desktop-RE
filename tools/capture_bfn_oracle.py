#!/usr/bin/env python3
"""Capture only redacted LSX structure from a normal BFN/EA Desktop launch."""

from __future__ import annotations

import argparse
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import frida


DEFAULT_LOG = Path.home() / "AppData/Local/Electronic Arts/EA Desktop/Logs/EADesktopVerbose.log"
WATCHED = {
    "EADesktop.exe",
    "EABackgroundService.exe",
    "EAAntiCheat.GameServiceLauncher.exe",
    "PVZBattleforNeighborville.exe",
}


def _shape(element: ET.Element, depth: int = 0) -> dict[str, object]:
    result: dict[str, object] = {"tag": element.tag, "fields": sorted(element.attrib)}
    if depth < 4:
        result["children"] = [_shape(child, depth + 1) for child in element]
    else:
        result["child_tags"] = [child.tag for child in element]
    return result


def _processes() -> list[dict[str, object]]:
    return sorted(
        (
            {"name": process.name, "pid": process.pid}
            for process in frida.get_local_device().enumerate_processes()
            if process.name in WATCHED
        ),
        key=lambda value: (str(value["name"]), int(value["pid"])),
    )


def _lsx_record(line: str) -> dict[str, object] | None:
    start = line.find("<LSX>")
    end = line.find("</LSX>", start)
    if start < 0 or end < 0:
        return None
    try:
        root = ET.fromstring(line[start : end + len("</LSX>")])
        outer = root[0]
        inner = outer[0]
    except (ET.ParseError, IndexError):
        return None
    timestamp = re.search(r"\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z)\]", line)
    record: dict[str, object] = {
        "timestamp": timestamp.group(1) if timestamp else None,
        "envelope": outer.tag,
        "message": inner.tag,
        "envelope_fields": sorted(outer.attrib),
        "message_fields": sorted(inner.attrib),
        "child_elements": [child.tag for child in inner],
        "shape": _shape(inner),
    }
    if inner.tag == "GetConfigResponse":
        record["facilities"] = [
            child.attrib.get("Facility", "") for child in inner if child.tag == "Service"
        ]
    if inner.tag == "ErrorSuccess":
        record["error_code"] = inner.attrib.get("Code")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--output", type=Path, default=Path("analysis/runtime/bfn_normal_launch_oracle.json"))
    parser.add_argument("--since", help="Extract existing redacted log events from this ISO UTC timestamp")
    args = parser.parse_args()
    log = args.log.resolve()
    if args.since:
        events = [
            record
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
            if (record := _lsx_record(line)) and record["timestamp"] and record["timestamp"] >= args.since
        ]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"schema": 1, "events": events}, indent=2), encoding="utf-8")
        print(f"saved {len(events)} redacted LSX events to {args.output}", flush=True)
        return
    offset = log.stat().st_size if log.exists() else 0
    pending = ""
    events: list[dict[str, object]] = []
    processes: list[dict[str, object]] = []
    last_processes: list[dict[str, object]] | None = None
    print("oracle capture ready; launch BFN normally from EA Desktop", flush=True)
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            if log.exists():
                size = log.stat().st_size
                if size < offset:
                    offset = 0
                    pending = ""
                if size > offset:
                    with log.open("rb") as handle:
                        handle.seek(offset)
                        chunk = handle.read(size - offset)
                    offset = size
                    pending += chunk.decode("utf-8", errors="replace")
                    lines = pending.split("\n")
                    pending = lines.pop()
                    for line in lines:
                        record = _lsx_record(line)
                        if record:
                            events.append(record)
                            print(f"LSX {record['envelope']}/{record['message']}", flush=True)
            current = _processes()
            if current != last_processes:
                processes.append({"at_seconds": round(args.seconds - (deadline - time.monotonic()), 2), "processes": current})
                print("processes=" + ",".join(str(x["name"]) for x in current), flush=True)
                last_processes = current
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"schema": 1, "duration_seconds": args.seconds, "events": events, "process_transitions": processes}, indent=2),
        encoding="utf-8",
    )
    print(f"saved {len(events)} redacted LSX events to {args.output}", flush=True)


if __name__ == "__main__":
    main()
