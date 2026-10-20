#!/usr/bin/env python3
"""Dump small, explicitly requested byte ranges from an IDA database.

This is intended for decoding short constant field names and lookup-table
entries while documenting protocol builders. It deliberately requires every
address and size on the command line and caps each read at 256 bytes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import idapro  # Must be the first IDA import.
import ida_auto
import ida_bytes
import ida_name


def parse_range(value: str) -> tuple[int, int]:
    address_text, separator, size_text = value.partition(":")
    if not separator:
        raise argparse.ArgumentTypeError("range must be ADDRESS:SIZE")
    address = int(address_text, 0)
    size = int(size_text, 0)
    if not 1 <= size <= 256:
        raise argparse.ArgumentTypeError("size must be between 1 and 256")
    return address, size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--range", action="append", required=True, type=parse_range)
    args = parser.parse_args()

    binary = args.binary.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"[idalib] opening {binary}", flush=True)
    result = idapro.open_database(str(binary), True)
    if result != 0:
        raise RuntimeError(f"Could not open {binary}; idalib returned {result}")
    try:
        ida_auto.auto_wait()
        records = []
        for address, size in args.range:
            data = ida_bytes.get_bytes(address, size)
            if data is None:
                records.append({"ea": hex(address), "size": size, "error": "unmapped"})
                continue
            records.append(
                {
                    "ea": hex(address),
                    "name": ida_name.get_name(address),
                    "size": size,
                    "hex": data.hex(),
                    "ascii": "".join(chr(byte) if 32 <= byte < 127 else "." for byte in data),
                }
            )
        output.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"[idalib] wrote {output} ({len(records)} ranges)", flush=True)
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
