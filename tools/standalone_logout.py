#!/usr/bin/env python3
"""Sign the standalone launcher out and forget the current account."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standalone_launcher.session import clear_standalone_session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokens", type=Path, default=Path("private/ea_tokens.dpapi"))
    parser.add_argument("--library", type=Path, default=Path("private/ea_library.dpapi"))
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("analysis/runtime/standalone_library_2026-10-17.json"),
    )
    args = parser.parse_args()
    removed = clear_standalone_session(
        token_store=args.tokens,
        library_store=args.library,
        summary_path=args.summary,
    )
    print(json.dumps({"logout": "succeeded", "removed": removed}, indent=2))


if __name__ == "__main__":
    main()
