#!/usr/bin/env python3
"""Extract targeted, redacted runtime log evidence without copying whole logs."""

import argparse
import hashlib
import json
import re
from pathlib import Path


CATEGORIES = {
    "auth": re.compile(
        r"login request|authentication change|access token|refresh token|persona.*loaded|"
        r"auth success|rememberme|login page|authenticated", re.I
    ),
    "library": re.compile(
        r"entitlement|catalog|content store|catalogstore|library|graphql", re.I
    ),
    "download_install": re.compile(
        r"jiturl|getdownloadurl|modifycontentflow|getcontentmanifest|preparepatchplan|"
        r"download(ing|ed)?|install(ing|ed|er)?|dip manifest|touchup|crc32|kvp|kpp", re.I
    ),
    "activation": re.compile(
        r"request.*license|license.*request|license files? valid|gametoken|denuvo|"
        r"online activation|reactivat", re.I
    ),
    "launch": re.compile(
        r"processing launch request|launch request approved|requestlicenseandlaunch|"
        r"processcoordinator|launching game|game process|ealaunch(helper|er)|"
        r"create process|starting executable|external.*launch", re.I
    ),
}


REDACTIONS = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"), r"\1<REDACTED>"),
    (re.compile(r"(?i)((?:access|refresh|id|auth|game)[_-]?token\s*[:=]\s*)[^\s,;&]+"), r"\1<REDACTED>"),
    (re.compile(r"(?i)([?&](?:access_token|refresh_token|id_token|code)=)[^&\s]+"), r"\1<REDACTED>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){1,2}\b"), "<JWT_REDACTED>"),
    (re.compile(r'(?i)("(?:valu|value|machineId|remid|sid|sessionId|userId|personaId)"\s*:\s*")[^"]+(\")'), r'\1<REDACTED>\2'),
    (re.compile(r"(?i)(\b(?:remid|sid|machineId|sessionId|userId|personaId)\s*[=:]\s*)[^\s,;\]}]+"), r"\1<REDACTED>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL_REDACTED>"),
    (re.compile(r"\b\d{12,}\b"), "<ID_REDACTED>"),
    (re.compile(r"(?i)C:\\Users\\[^\\\s]+"), r"C:\\Users\\<USER>"),
]


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text.rstrip("\r\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--max-per-category-per-file", type=int, default=500)
    args = parser.parse_args()

    result = {"schema": 1, "sources": [], "categories": {name: [] for name in CATEGORIES}}
    for source in args.logs:
        source = source.resolve()
        if not source.is_file():
            continue
        result["sources"].append({
            "path": str(source),
            "size": source.stat().st_size,
            "sha256": file_hash(source),
        })
        counts = {name: 0 for name in CATEGORIES}
        with source.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, 1):
                for category, pattern in CATEGORIES.items():
                    if counts[category] >= args.max_per_category_per_file:
                        continue
                    if "TelemetryManagerV2::processEvent" in line:
                        if category != "auth" or not re.search(r"user\.(?:auth|accs|lgin)\.ends", line, re.I):
                            continue
                    if pattern.search(line):
                        result["categories"][category].append({
                            "source": str(source),
                            "line": line_number,
                            "text": redact(line),
                        })
                        counts[category] += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
