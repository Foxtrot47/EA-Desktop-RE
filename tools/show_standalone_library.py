#!/usr/bin/env python3
"""Print the standalone owned-game view from the protected library snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_launcher.ea_custom_launcher import discover_installed_games
from standalone_launcher.library import load_snapshot_dpapi
from standalone_launcher.model import build_library_records, visible_owned_games


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=Path("private/ea_library.dpapi"))
    parser.add_argument("--all", action="store_true", help="include disabled products and add-ons")
    args = parser.parse_args()
    records = build_library_records(load_snapshot_dpapi(args.snapshot), discover_installed_games())
    selected = records if args.all else visible_owned_games(records)
    print(json.dumps([value.to_dict() for value in selected], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
