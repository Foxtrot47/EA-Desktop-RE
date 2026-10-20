#!/usr/bin/env python3
"""Build a compact static-analysis index for a PE file using IDA 9.x idalib."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

import idapro  # Must be imported before other IDA modules.
import ida_auto
import ida_entry
import ida_funcs
import ida_ida
import ida_idaapi
import ida_nalt
import ida_name
import ida_segment
import ida_xref
import idautils


KEYWORD_GROUPS = {
    "auth": [
        "oauth", "authorize", "authorization", "signin", "sign-in", "login",
        "logout", "access_token", "refresh_token", "id_token", "pkce",
        "code_verifier", "code_challenge", "redirect_uri", "authentication",
    ],
    "library": [
        "entitlement", "library", "catalog", "offerid", "offer_id", "mastertitle",
        "contentid", "content_id", "ownedgame", "gamedata", "productid",
    ],
    "download_install": [
        "download", "install", "manifest", "chunk", "dip", "installer",
        "staging", "unpack", "verify", "repair", "update", "patch",
    ],
    "activation": [
        "activation", "activate", "license", "licence", "gametoken",
        "game_token", "drm", "offline mode", "machinehash",
    ],
    "launch": [
        "launchgame", "launch_game", "launcher", "createprocess", "process",
        "commandline", "command_line", "executablepath", "overlay", "igo",
        "steam", "epic", "egs", "link2ea",
    ],
    "transport": [
        "http://", "https://", "wss://", "grpc", "websocket", "protobuf",
        "content-type", "user-agent", "localhost", "127.0.0.1",
    ],
    "storage": [
        "sqlite", ".db", "programdata", "localappdata", "appdata", "cache",
        "registry", "credential", "keychain", "dpapi", "cryptprotectdata",
    ],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def safe_text(value) -> str:
    try:
        return str(value)
    except Exception:
        return repr(value)


def containing_function(ea: int):
    func = ida_funcs.get_func(ea)
    if func is None:
        return None
    return {
        "start_ea": hex(func.start_ea),
        "end_ea": hex(func.end_ea),
        "name": ida_funcs.get_func_name(func.start_ea),
    }


def collect_imports():
    modules = []
    for index in range(ida_nalt.get_import_module_qty()):
        symbols = []

        def callback(ea, name, ordinal):
            symbols.append({"ea": hex(ea), "name": name, "ordinal": ordinal})
            return True

        module_name = ida_nalt.get_import_module_name(index)
        ida_nalt.enum_import_names(index, callback)
        modules.append({"module": module_name, "symbols": symbols})
    return modules


def collect_exports():
    exports = []
    count = ida_entry.get_entry_qty()
    for index in range(count):
        ordinal = ida_entry.get_entry_ordinal(index)
        ea = ida_entry.get_entry(ordinal)
        exports.append({
            "ordinal": ordinal,
            "ea": hex(ea),
            "name": ida_entry.get_entry_name(ordinal) or ida_name.get_name(ea),
        })
    return exports


def collect_segments():
    rows = []
    for index in range(ida_segment.get_segm_qty()):
        seg = ida_segment.getnseg(index)
        rows.append({
            "name": ida_segment.get_segm_name(seg),
            "class": ida_segment.get_segm_class(seg),
            "start_ea": hex(seg.start_ea),
            "end_ea": hex(seg.end_ea),
            "permissions": seg.perm,
            "bitness": seg.bitness,
        })
    return rows


def collect_keyword_hits(max_hits_per_group: int):
    compiled = {
        group: [(term, re.compile(re.escape(term), re.IGNORECASE)) for term in terms]
        for group, terms in KEYWORD_GROUPS.items()
    }
    output = {group: [] for group in KEYWORD_GROUPS}
    total_strings = 0
    for item in idautils.Strings():
        total_strings += 1
        text = safe_text(item)
        for group, patterns in compiled.items():
            if len(output[group]) >= max_hits_per_group:
                continue
            matched_terms = [term for term, pattern in patterns if pattern.search(text)]
            if not matched_terms:
                continue
            xrefs = []
            for xref in idautils.XrefsTo(item.ea):
                xrefs.append({
                    "from_ea": hex(xref.frm),
                    "type": xref.type,
                    "function": containing_function(xref.frm),
                })
            output[group].append({
                "ea": hex(item.ea),
                "text": text,
                "matched_terms": matched_terms,
                "xrefs": xrefs,
            })
    return total_strings, output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-hits-per-group", type=int, default=1500)
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
        strings_count, keyword_hits = collect_keyword_hits(args.max_hits_per_group)
        function_starts = list(idautils.Functions())
        result = {
            "schema": 1,
            "source": {
                "path": str(binary),
                "size": binary.stat().st_size,
                "sha256": sha256(binary),
            },
            "database": {
                "image_base": hex(ida_nalt.get_imagebase()),
                "is_64bit": bool(ida_ida.inf_is_64bit()),
                "min_ea": hex(ida_ida.inf_get_min_ea()),
                "max_ea": hex(ida_ida.inf_get_max_ea()),
                "function_count": len(function_starts),
                "string_count": strings_count,
            },
            "segments": collect_segments(),
            "imports": collect_imports(),
            "exports": collect_exports(),
            "keyword_groups": KEYWORD_GROUPS,
            "keyword_hits": keyword_hits,
        }
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[idalib] wrote {output}", flush=True)
    finally:
        idapro.close_database()


if __name__ == "__main__":
    main()
