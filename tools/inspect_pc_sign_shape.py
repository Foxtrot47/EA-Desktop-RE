#!/usr/bin/env python3
"""Decode only the non-secret structure of a pc_sign value found in EA logs.

The emitted report never contains the source value, signature bytes, cookies,
tokens, or identifier values. Identifier-like payload fields are summarized by
JSON type and encoded length so protocol work can proceed without retaining
account or machine data.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


URL_RE = re.compile(r"https://accounts\.ea\.com/connect/auth\?[^\]\s]+")


def decode_segment(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def describe(value: object) -> dict[str, object]:
    result: dict[str, object] = {"json_type": type(value).__name__}
    if isinstance(value, str):
        result["length"] = len(value)
    elif isinstance(value, (list, dict)):
        result["item_count"] = len(value)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("logs", nargs="+", type=Path)
    args = parser.parse_args()

    candidate: str | None = None
    source_name: str | None = None
    for path in args.logs:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = URL_RE.search(line)
            if not match:
                continue
            values = parse_qs(urlsplit(match.group(0)).query).get("pc_sign")
            if values:
                candidate = values[0]
                source_name = path.name

    if not candidate:
        raise SystemExit("No pc_sign parameter found")

    segments = candidate.split(".")
    if len(segments) != 2:
        raise SystemExit(f"Unexpected pc_sign segment count: {len(segments)}")
    payload_bytes = decode_segment(segments[0])
    signature_bytes = decode_segment(segments[1])
    payload = json.loads(payload_bytes)

    safe_constants = {"av", "sv"}
    fields = {}
    for key, value in payload.items():
        entry = describe(value)
        if key in safe_constants and isinstance(value, str):
            entry["value"] = value
        fields[key] = entry

    report = {
        "schema": 1,
        "source_log_name": source_name,
        "segment_count": len(segments),
        "payload_encoding": "base64url without padding",
        "payload_format": "JSON UTF-8",
        "payload_length": len(payload_bytes),
        "signature_encoding": "base64url without padding",
        "signature_length": len(signature_bytes),
        "fields": fields,
        "redaction": "All identifier values and signature bytes are omitted.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
