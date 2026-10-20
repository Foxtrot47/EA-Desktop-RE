#!/usr/bin/env python3
"""Decompile functions that reference strings matching supplied regular expressions."""

import argparse
import hashlib
import json
import re
from pathlib import Path

import idapro  # Must be first IDA import.
import ida_auto
import ida_funcs
import ida_hexrays
import idautils


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def function_record(start_ea: int, pseudocode_limit: int):
    func = ida_funcs.get_func(start_ea)
    if func is None:
        return None
    callers = []
    for ref in idautils.CodeRefsTo(func.start_ea, False):
        parent = ida_funcs.get_func(ref)
        callers.append({
            "call_ea": hex(ref),
            "function_ea": hex(parent.start_ea) if parent else None,
            "function_name": ida_funcs.get_func_name(parent.start_ea) if parent else None,
        })
    callees = {}
    for head in idautils.FuncItems(func.start_ea):
        for target in idautils.CodeRefsFrom(head, False):
            called = ida_funcs.get_func(target)
            if called:
                callees[called.start_ea] = ida_funcs.get_func_name(called.start_ea)
    try:
        cfunc = ida_hexrays.decompile(func.start_ea)
        pseudocode = str(cfunc) if cfunc else None
        decompile_error = None
    except Exception as exc:
        pseudocode = None
        decompile_error = repr(exc)
    if pseudocode and len(pseudocode) > pseudocode_limit:
        pseudocode = pseudocode[:pseudocode_limit] + "\n/* pseudocode truncated by tool */"
    return {
        "start_ea": hex(func.start_ea),
        "end_ea": hex(func.end_ea),
        "name": ida_funcs.get_func_name(func.start_ea),
        "callers": callers,
        "callees": [
            {"ea": hex(ea), "name": name}
            for ea, name in sorted(callees.items())
        ],
        "pseudocode": pseudocode,
        "decompile_error": decompile_error,
        "referenced_strings": [],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--term", action="append", required=True, help="case-insensitive regex")
    parser.add_argument("--max-functions", type=int, default=80)
    parser.add_argument("--pseudocode-limit", type=int, default=100000)
    args = parser.parse_args()

    binary = args.binary.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    patterns = [re.compile(term, re.IGNORECASE) for term in args.term]

    print(f"[idalib] opening {binary}", flush=True)
    open_result = idapro.open_database(str(binary), True)
    if open_result != 0:
        raise RuntimeError(f"Could not open {binary}; idalib returned {open_result}")
    try:
        ida_auto.auto_wait()
        matches = []
        selected_functions = {}
        all_strings = list(idautils.Strings())
        string_by_ea = {item.ea: str(item) for item in all_strings}
        for item in all_strings:
            text = str(item)
            matching_terms = [args.term[i] for i, pattern in enumerate(patterns) if pattern.search(text)]
            if not matching_terms:
                continue
            xrefs = []
            for xref in idautils.XrefsTo(item.ea):
                func = ida_funcs.get_func(xref.frm)
                function_ea = func.start_ea if func else None
                if function_ea is not None and len(selected_functions) < args.max_functions:
                    selected_functions[function_ea] = None
                xrefs.append({
                    "from_ea": hex(xref.frm),
                    "function_ea": hex(function_ea) if function_ea is not None else None,
                    "function_name": ida_funcs.get_func_name(function_ea) if function_ea is not None else None,
                })
            matches.append({
                "ea": hex(item.ea),
                "text": text,
                "matching_terms": matching_terms,
                "xrefs": xrefs,
            })

        functions = []
        for function_ea in selected_functions:
            record = function_record(function_ea, args.pseudocode_limit)
            if record is None:
                continue
            func = ida_funcs.get_func(function_ea)
            seen = set()
            for head in idautils.FuncItems(func.start_ea):
                for target in idautils.DataRefsFrom(head):
                    if target in string_by_ea and target not in seen:
                        seen.add(target)
                        record["referenced_strings"].append({"ea": hex(target), "text": string_by_ea[target]})
            functions.append(record)

        result = {
            "schema": 1,
            "source": {"path": str(binary), "sha256": sha256(binary)},
            "terms": args.term,
            "matching_strings": matches,
            "functions": functions,
            "limits": {
                "max_functions": args.max_functions,
                "pseudocode_char_limit_per_function": args.pseudocode_limit,
                "selected_function_count": len(functions),
            },
        }
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[idalib] wrote {output} ({len(functions)} functions)", flush=True)
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
