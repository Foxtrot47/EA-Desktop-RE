#!/usr/bin/env python3
"""Decompile IDA functions whose symbol names contain requested text."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import idapro  # Must be the first IDA import.
import ida_auto
import ida_funcs
import idautils

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
    parser.add_argument("--max-functions", type=int, default=100)
    parser.add_argument("--pseudocode-limit", type=int, default=250_000)
    args = parser.parse_args()

    binary = args.binary.resolve()
    output = args.output.resolve()
    terms = [term.casefold() for term in args.name_contains]
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"[idalib] opening {binary}", flush=True)
    open_result = idapro.open_database(str(binary), True)
    if open_result != 0:
        raise RuntimeError(f"Could not open {binary}; idalib returned {open_result}")
    try:
        ida_auto.auto_wait()
        addresses = []
        for address in idautils.Functions():
            name = ida_funcs.get_func_name(address)
            if any(term in name.casefold() for term in terms):
                addresses.append(address)
                if len(addresses) >= args.max_functions:
                    break
        functions = [decompile_address(address, args.pseudocode_limit) for address in addresses]
        result = {
            "schema": 1,
            "source": {"path": str(binary), "sha256": sha256(binary)},
            "name_terms": args.name_contains,
            "functions": functions,
        }
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[idalib] wrote {output} ({len(functions)} matching functions)", flush=True)
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
