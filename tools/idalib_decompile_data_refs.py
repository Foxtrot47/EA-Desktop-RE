#!/usr/bin/env python3
"""Decompile functions containing references to explicit data addresses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import idapro  # Must be first.
import ida_auto
import ida_funcs
import idautils

from idalib_decompile_addresses import decompile_address, sha256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--address", action="append", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--pseudocode-limit", type=int, default=250_000)
    args = parser.parse_args()

    binary = args.binary.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"[idalib] opening {binary}", flush=True)
    if idapro.open_database(str(binary), True) != 0:
        raise RuntimeError(f"Could not open {binary}")
    try:
        ida_auto.auto_wait()
        references = []
        functions: set[int] = set()
        for address in args.address:
            address_refs = []
            for xref in idautils.XrefsTo(address):
                function = ida_funcs.get_func(xref.frm)
                if function:
                    functions.add(function.start_ea)
                address_refs.append(
                    {
                        "from_ea": hex(xref.frm),
                        "function_ea": hex(function.start_ea) if function else None,
                        "function_name": ida_funcs.get_func_name(function.start_ea) if function else None,
                    }
                )
            references.append({"address": hex(address), "xrefs": address_refs})
        result = {
            "schema": 1,
            "source": {"path": str(binary), "sha256": sha256(binary)},
            "references": references,
            "functions": [
                decompile_address(address, args.pseudocode_limit)
                for address in sorted(functions)
            ],
        }
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[idalib] wrote {output} ({len(functions)} functions)", flush=True)
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
