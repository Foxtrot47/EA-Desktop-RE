#!/usr/bin/env python3
"""Decompile an explicit set of function addresses from a PE with IDALib."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import idapro  # Must be the first IDA import.
import ida_auto
import ida_funcs
import ida_hexrays
import idautils


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def decompile_address(address: int, pseudocode_limit: int) -> dict[str, object]:
    func = ida_funcs.get_func(address)
    if func is None:
        return {
            "requested_ea": hex(address),
            "error": "address is not inside a recognized function",
        }

    callers = []
    for ref in idautils.CodeRefsTo(func.start_ea, False):
        parent = ida_funcs.get_func(ref)
        callers.append(
            {
                "call_ea": hex(ref),
                "function_ea": hex(parent.start_ea) if parent else None,
                "function_name": ida_funcs.get_func_name(parent.start_ea) if parent else None,
            }
        )

    callees: dict[int, str] = {}
    referenced_strings: dict[int, str] = {}
    strings = {item.ea: str(item) for item in idautils.Strings()}
    for head in idautils.FuncItems(func.start_ea):
        for target in idautils.CodeRefsFrom(head, False):
            called = ida_funcs.get_func(target)
            if called:
                callees[called.start_ea] = ida_funcs.get_func_name(called.start_ea)
        for target in idautils.DataRefsFrom(head):
            if target in strings:
                referenced_strings[target] = strings[target]

    try:
        cfunc = ida_hexrays.decompile(func.start_ea)
        pseudocode = str(cfunc) if cfunc else None
        decompile_error = None
    except Exception as exc:  # IDA exposes several provider-specific failures.
        pseudocode = None
        decompile_error = repr(exc)

    truncated = bool(pseudocode and len(pseudocode) > pseudocode_limit)
    if truncated:
        pseudocode = pseudocode[:pseudocode_limit] + "\n/* pseudocode truncated by tool */"

    return {
        "requested_ea": hex(address),
        "start_ea": hex(func.start_ea),
        "end_ea": hex(func.end_ea),
        "name": ida_funcs.get_func_name(func.start_ea),
        "callers": callers,
        "callees": [
            {"ea": hex(ea), "name": name} for ea, name in sorted(callees.items())
        ],
        "referenced_strings": [
            {"ea": hex(ea), "text": text} for ea, text in sorted(referenced_strings.items())
        ],
        "pseudocode": pseudocode,
        "pseudocode_truncated": truncated,
        "decompile_error": decompile_error,
    }


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
    open_result = idapro.open_database(str(binary), True)
    if open_result != 0:
        raise RuntimeError(f"Could not open {binary}; idalib returned {open_result}")
    try:
        ida_auto.auto_wait()
        functions = [decompile_address(address, args.pseudocode_limit) for address in args.address]
        result = {
            "schema": 1,
            "source": {"path": str(binary), "sha256": sha256(binary)},
            "requested_addresses": [hex(address) for address in args.address],
            "functions": functions,
        }
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[idalib] wrote {output} ({len(functions)} requested functions)", flush=True)
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
