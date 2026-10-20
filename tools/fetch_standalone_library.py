#!/usr/bin/env python3
"""Retrieve the signed-in user's EA library without using EA Desktop."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make direct ``python tools/fetch_standalone_library.py`` invocation work.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standalone_launcher.library import (
    GraphQlClient,
    load_snapshot_dpapi,
    retrieve_library,
    sanitized_summary,
    save_snapshot_dpapi,
)
from standalone_launcher.login import load_tokens_dpapi


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokens", type=Path, default=Path("private/ea_tokens.dpapi"))
    parser.add_argument("--output", type=Path, default=Path("private/ea_library.dpapi"))
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("analysis/runtime/standalone_library_2026-10-17.json"),
    )
    args = parser.parse_args()

    tokens = load_tokens_dpapi(args.tokens)
    def progress(stage, counts):
        print(json.dumps({"stage": stage, **counts}), flush=True)

    snapshot = retrieve_library(GraphQlClient(tokens.access_token), progress)
    save_snapshot_dpapi(args.output, snapshot)
    verified = load_snapshot_dpapi(args.output)
    if verified != snapshot:
        raise RuntimeError("library DPAPI round-trip failed")

    summary = sanitized_summary(snapshot)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": "succeeded", "private_snapshot": str(args.output.resolve()), **summary}, indent=2))


if __name__ == "__main__":
    main()
