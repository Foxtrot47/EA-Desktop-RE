#!/usr/bin/env python3
"""List unique string literals from selected functions in a decompilation JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


STRING_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("addresses", nargs="+")
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    functions = {item["start_ea"].lower(): item for item in data["functions"]}

    for address in args.addresses:
        function = functions.get(address.lower())
        print(f"\n### {address}")
        if function is None:
            print("<not captured>")
            continue

        print(function.get("name", ""))
        literals: list[str] = []
        for line in function.get("pseudocode", "").splitlines():
            for value in STRING_LITERAL.findall(line):
                if value and value not in literals:
                    literals.append(value)
        for value in literals:
            print(repr(value))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
