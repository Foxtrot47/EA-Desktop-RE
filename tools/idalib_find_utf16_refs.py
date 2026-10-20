#!/usr/bin/env python3
"""Find UTF-16 literals and their code references in an IDALib database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import idapro  # Must be imported before the other IDA modules.
import ida_auto
import ida_bytes
import ida_funcs
import ida_segment
import idautils


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--literal", action="append", default=[])
    parser.add_argument("--ascii-literal", action="append", default=[])
    args = parser.parse_args()
    if not args.literal and not args.ascii_literal:
        parser.error("at least one literal is required")

    binary = args.binary.resolve()
    if idapro.open_database(str(binary), True) != 0:
        raise RuntimeError(f"Could not open {binary}")
    try:
        ida_auto.auto_wait()
        needles = {literal: literal.encode("utf-16le") for literal in args.literal}
        needles.update({literal: literal.encode("ascii") for literal in args.ascii_literal})
        matches = []
        segment = ida_segment.get_first_seg()
        overlap = max(len(needle) for needle in needles.values()) - 1
        while segment:
            cursor = segment.start_ea
            while cursor < segment.end_ea:
                size = min(16 * 1024 * 1024, segment.end_ea - cursor)
                data = ida_bytes.get_bytes(cursor, size)
                if not data:
                    cursor += size
                    continue
                for literal, needle in needles.items():
                    offset = 0
                    while (offset := data.find(needle, offset)) >= 0:
                        ea = cursor + offset
                        refs = []
                        for xref in idautils.XrefsTo(ea):
                            function = ida_funcs.get_func(xref.frm)
                            refs.append({
                                "from_ea": hex(xref.frm),
                                "function_ea": hex(function.start_ea) if function else None,
                            })
                        matches.append({"literal": literal, "ea": hex(ea), "xrefs": refs})
                        offset += len(needle)
                cursor += max(1, size - overlap)
            segment = ida_segment.get_next_seg(segment.start_ea)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"matches": matches}, indent=2), encoding="utf-8")
        print(f"[idalib] wrote {args.output} ({len(matches)} matches)", flush=True)
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
