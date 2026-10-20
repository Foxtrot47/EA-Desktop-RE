#!/usr/bin/env python3
"""Decode Origin Online Activation UTF-16 literals used by a PE.

The current OOA code constructs an encoded std::wstring immediately before
passing it to a shared decoder.  This tool finds every function that calls the
decoder, extracts directly referenced constant buffers from its pseudocode,
and records only the decoded constants.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import idapro  # Must be the first IDA import.
import ida_auto
import ida_bytes
import ida_funcs
import ida_hexrays
import idautils


CONSTRUCTOR = re.compile(
    r"sub_[0-9A-Fa-f]+\([^,]+,\s*&?(?:unk_|off_|byte_|word_|dword_|qword_)?"
    r"([0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+|\d+)u?\)"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _next_key(value: int) -> int:
    return (((value | 0xFFFE) << 14) | ((value >> 1) & 0x3FFF)) & 0xFFFF


def decode_oob_utf16(data: bytes) -> str:
    if len(data) % 2 or len(data) < 48:
        raise ValueError("OOA string must contain at least 24 UTF-16 code units")
    words = list(struct.unpack("<" + "H" * (len(data) // 2), data))
    payload = words[12:-12]
    if "".join(chr(value) for value in words[:12]) == "**OB_START**":
        decoded = payload
    else:
        key = words[0]
        decoded = []
        for value in payload:
            decoded.append(value ^ key if value else 0)
            key = _next_key(key)
    raw = b"".join(struct.pack("<H", value) for value in decoded)
    return raw.decode("utf-16le").rstrip("\0")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--decoder", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--max-code-units", type=int, default=512)
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
        callers: dict[int, list[int]] = {}
        for reference in idautils.CodeRefsTo(args.decoder, False):
            function = ida_funcs.get_func(reference)
            if function:
                callers.setdefault(function.start_ea, []).append(reference)

        records: dict[int, dict[str, object]] = {}
        errors: list[dict[str, object]] = []
        for function_ea, call_sites in sorted(callers.items()):
            try:
                cfunc = ida_hexrays.decompile(function_ea)
                pseudocode = str(cfunc) if cfunc else ""
            except Exception as exc:
                errors.append({"function_ea": hex(function_ea), "error": repr(exc)})
                continue
            for match in CONSTRUCTOR.finditer(pseudocode):
                address = int(match.group(1), 16)
                code_units = int(match.group(2), 0)
                if not 24 <= code_units <= args.max_code_units:
                    continue
                data = ida_bytes.get_bytes(address, code_units * 2)
                if data is None:
                    continue
                try:
                    decoded = decode_oob_utf16(data)
                except (UnicodeDecodeError, ValueError):
                    continue
                if not decoded or any(ord(character) < 9 for character in decoded):
                    continue
                record = records.setdefault(
                    address,
                    {
                        "ea": hex(address),
                        "code_units": code_units,
                        "text": decoded,
                        "callers": [],
                    },
                )
                record["callers"].append(
                    {
                        "function_ea": hex(function_ea),
                        "function_name": ida_funcs.get_func_name(function_ea),
                        "decoder_call_sites": [hex(value) for value in call_sites],
                    }
                )

        document = {
            "schema": 1,
            "source": {"path": str(binary), "sha256": sha256(binary)},
            "decoder_ea": hex(args.decoder),
            "caller_function_count": len(callers),
            "decoded": [records[address] for address in sorted(records)],
            "errors": errors,
        }
        output.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"[idalib] wrote {output} ({len(records)} decoded constants from {len(callers)} callers)",
            flush=True,
        )
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
