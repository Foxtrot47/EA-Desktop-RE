#!/usr/bin/env python3
"""Export an explicitly bounded IDA disassembly range as JSON.

This is intentionally small and read-only.  It is useful when Hex-Rays has
inferred an incomplete prototype and the call-site register setup matters.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import idapro  # Must be imported before other IDA modules.
import ida_auto
import ida_bytes
import ida_lines
import ida_name


def parse_range(value: str) -> tuple[int, int]:
    start_text, separator, end_text = value.partition(":")
    if not separator:
        raise argparse.ArgumentTypeError("range must be START:END")
    start, end = int(start_text, 0), int(end_text, 0)
    if end <= start or end - start > 0x10000:
        raise argparse.ArgumentTypeError("range must be ascending and at most 64 KiB")
    return start, end


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--range", required=True, type=parse_range)
    args = parser.parse_args()

    binary = args.binary.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    start, end = args.range

    print(f"[idalib] opening {binary}", flush=True)
    result = idapro.open_database(str(binary), True)
    if result != 0:
        raise RuntimeError(f"Could not open {binary}; idalib returned {result}")
    try:
        ida_auto.auto_wait()
        records = []
        ea = start
        while ea < end:
            line = ida_lines.generate_disasm_line(ea, 0)
            size = ida_bytes.get_item_size(ea)
            if not size:
                size = 1
            records.append(
                {
                    "ea": hex(ea),
                    "name": ida_name.get_name(ea),
                    "size": size,
                    "text": ida_lines.tag_remove(line or ""),
                }
            )
            ea += size
        output.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"[idalib] wrote {output} ({len(records)} items)", flush=True)
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
