#!/usr/bin/env python3
"""Find named IDA items and decompile function pointers stored in them."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import idapro  # Must be first.
import ida_auto
import ida_bytes
import ida_funcs
import ida_name

from idalib_decompile_addresses import decompile_address


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--name-contains", action="append", required=True)
    parser.add_argument("--qwords", type=int, default=8)
    args = parser.parse_args()
    binary = args.binary.resolve()
    terms = [value.casefold() for value in args.name_contains]
    if idapro.open_database(str(binary), True) != 0:
        raise RuntimeError(f"Could not open {binary}")
    try:
        ida_auto.auto_wait()
        matches = []
        targets: set[int] = set()
        for index in range(ida_name.get_nlist_size()):
            name = ida_name.get_nlist_name(index)
            if not any(term in name.casefold() for term in terms):
                continue
            ea = ida_name.get_nlist_ea(index)
            pointers = []
            for offset in range(0, args.qwords * 8, 8):
                value = ida_bytes.get_qword(ea + offset)
                function = ida_funcs.get_func(value)
                if function:
                    targets.add(function.start_ea)
                pointers.append(
                    {
                        "offset": offset,
                        "value": hex(value),
                        "function_ea": hex(function.start_ea) if function else None,
                        "function_name": ida_funcs.get_func_name(function.start_ea) if function else None,
                    }
                )
            matches.append({"ea": hex(ea), "name": name, "qwords": pointers})
        functions = [decompile_address(ea, 250_000) for ea in sorted(targets)]
        result = {
            "schema": 1,
            "source": {"path": str(binary), "sha256": sha256(binary)},
            "terms": args.name_contains,
            "matches": matches,
            "functions": functions,
        }
        args.output.resolve().write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[idalib] wrote {args.output} ({len(matches)} names, {len(functions)} functions)", flush=True)
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
