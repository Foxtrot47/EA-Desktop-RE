#!/usr/bin/env python3
"""Find named data tables and decompile function pointers stored in them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import idapro  # Must be first.
import ida_auto
import ida_bytes
import ida_funcs
import ida_name

from idalib_decompile_addresses import decompile_address, sha256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--name-contains", action="append", required=True)
    parser.add_argument("--slots", type=int, default=10)
    parser.add_argument("--pseudocode-limit", type=int, default=250_000)
    args = parser.parse_args()
    terms = [term.casefold() for term in args.name_contains]
    binary = args.binary.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"[idalib] opening {binary}", flush=True)
    if idapro.open_database(str(binary), True) != 0:
        raise RuntimeError(f"Could not open {binary}")
    try:
        ida_auto.auto_wait()
        tables = []
        function_addresses: set[int] = set()
        for index in range(ida_name.get_nlist_size()):
            name = ida_name.get_nlist_name(index)
            if not any(term in name.casefold() for term in terms):
                continue
            address = ida_name.get_nlist_ea(index)
            slots = []
            for slot in range(args.slots):
                pointer = ida_bytes.get_qword(address + slot * 8)
                function = ida_funcs.get_func(pointer)
                slots.append(
                    {
                        "slot": slot,
                        "ea": hex(address + slot * 8),
                        "value": hex(pointer),
                        "function": ida_funcs.get_func_name(function.start_ea) if function else None,
                    }
                )
                if function:
                    function_addresses.add(function.start_ea)
            tables.append({"ea": hex(address), "name": name, "slots": slots})
        result = {
            "schema": 1,
            "source": {"path": str(binary), "sha256": sha256(binary)},
            "name_terms": args.name_contains,
            "tables": tables,
            "functions": [
                decompile_address(address, args.pseudocode_limit)
                for address in sorted(function_addresses)
            ],
        }
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"[idalib] wrote {output} ({len(tables)} tables, {len(function_addresses)} functions)",
            flush=True,
        )
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
