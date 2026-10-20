#!/usr/bin/env python3
"""Render or explicitly run a protected DiP manifest's touchup command."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standalone_launcher.bootstrap import dpapi_unprotect
from standalone_launcher.finalize import build_touchup_invocation, run_touchup
from standalone_launcher.manifest import parse_dip_manifest


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run by default; --execute runs EA touchup.")
    parser.add_argument("offer_id")
    parser.add_argument("--install-location", type=Path, required=True)
    parser.add_argument("--locale", default="en_US")
    parser.add_argument("--operation", choices=("install", "update", "repair"), default="install")
    parser.add_argument("--metadata", type=Path, default=Path("private/package_metadata"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    protected = args.metadata / safe_name(args.offer_id) / "installerdata.xml.dpapi"
    manifest = parse_dip_manifest(dpapi_unprotect(protected.read_bytes()))
    invocation = build_touchup_invocation(
        manifest,
        args.install_location,
        locale=args.locale,
        operation=args.operation,
    )
    print(
        json.dumps(
            {
                "offer_id": args.offer_id,
                "operation": args.operation,
                "executable": str(invocation.executable),
                "arguments": invocation.arguments,
                "working_directory": str(invocation.working_directory),
                "execute": args.execute,
            },
            indent=2,
        ),
        flush=True,
    )
    if args.execute:
        code = run_touchup(invocation)
        print(json.dumps({"touchup_exit_code": code}, indent=2))
        if code != 0:
            raise SystemExit(code)


if __name__ == "__main__":
    main()
