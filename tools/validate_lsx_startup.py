#!/usr/bin/env python3
"""Compare generated LSX startup response schemas with a local normal launch."""

from __future__ import annotations

from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from standalone_launcher.library import load_snapshot_dpapi
from standalone_launcher.lsx_startup import startup_reply


LOG = Path.home() / "AppData/Local/Electronic Arts/EA Desktop/Logs/EADesktopVerbose.log"


def main() -> None:
    snapshot = load_snapshot_dpapi(Path("private/ea_library.dpapi"))
    messages = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if "2026-10-19T18:26:" not in line or "<LSX>" not in line:
            continue
        xml = line[line.index("<LSX>") : line.index("</LSX>") + len("</LSX>")]
        messages.append(ET.fromstring(xml)[0])
    checked = 0
    failures = []
    for current, following in zip(messages, messages[1:]):
        if current.tag != "Request" or following.tag != "Response":
            continue
        generated = startup_reply(current, snapshot)
        if generated is None:
            continue
        expected = following[0]
        actual = ET.fromstring(generated)[0][0]
        if actual.tag != expected.tag or set(actual.attrib) != set(expected.attrib):
            failures.append((current[0].tag, actual.tag, expected.tag))
        checked += 1
    print(f"checked {checked} startup reply schemas; failures={len(failures)}")
    if failures:
        print(failures)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
