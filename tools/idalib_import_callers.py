#!/usr/bin/env python3
"""List functions that reference selected PE imports in an IDALib database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import idapro  # Must be the first IDA import.
import ida_auto
import ida_funcs
import ida_nalt
import idautils


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--contains", action="append", required=True)
    args = parser.parse_args()
    terms = tuple(term.casefold() for term in args.contains)
    if idapro.open_database(str(args.binary.resolve()), True) != 0:
        raise RuntimeError("could not open IDA database")
    try:
        ida_auto.auto_wait()
        matches: list[dict[str, object]] = []
        for index in range(ida_nalt.get_import_module_qty()):
            module = ida_nalt.get_import_module_name(index)

            def visit(ea: int, name: str | None, ordinal: int) -> bool:
                if not name or not any(term in name.casefold() for term in terms):
                    return True
                callers = []
                for xref in idautils.XrefsTo(ea):
                    function = ida_funcs.get_func(xref.frm)
                    callers.append({
                        "reference": hex(xref.frm),
                        "function": hex(function.start_ea) if function else None,
                        "function_name": ida_funcs.get_func_name(function.start_ea)
                        if function else None,
                    })
                matches.append({"module": module, "name": name, "ea": hex(ea), "callers": callers})
                return True

            ida_nalt.enum_import_names(index, visit)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(matches, indent=2), encoding="utf-8")
        print(f"wrote {len(matches)} matching imports")
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
