#!/usr/bin/env python3
"""Extract a redacted auth/library timeline from EA Desktop text logs.

The output deliberately keeps control-flow events and endpoint paths while
removing credentials, cookies, OAuth one-time values, user IDs, and local user
names. It never parses the protected cache files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


AUTH = re.compile(
    r"restoreRememberMeCookiesFromFile|LoginUIHandler::(?:login|directLogin|uiLogin)|"
    r"loadCachedPersonaInfo|loadCachedAccessTokenDataLocally|handleLoadedToken|"
    r"requestAuthCode|requestAccessToken|AccessTokenRequestor::parseResponse|"
    r"accounts\.ea\.com/connect/(?:auth|token)|EventAuthenticationChanged|"
    r"awaitingAuthentication|EventPersonaeUpdated|getCurrentUser|"
    r"user\.(?:auth|accs|lgin)\.|ClientSignoutRequest|EventInitiateSignOut|"
    r"SignoutInitiated|AccountSignOut|LoginHandler::logout|AccessTokenHandler::reset|"
    r"removeCachedFile|clearEntitlementStoreCache|AuthViewHolder|"
    r"Handling Authentication Success|Cookies discarded|removeCookiesByName|"
    r"UserSession ended",
    re.I,
)

LIBRARY = re.compile(
    r"UserSessionChanged|requestContentRefresh|NucleusEntitlementStore|"
    r"getLegacyEntitlements|getLegacyCatalogDefs|Nucleus Query|Catalog Query|"
    r"CacheTooOld|cache.*age|contentStoreCacheMaxLifetime|schedul.*refresh|reconcileStores|"
    r"buildMapOfferIdToBaseSlug|sendCacheUpdated|Catalog(?:Entries)?Update|"
    r"EntitlementCacheUpdated|EntitlementDataLoaded|EventEntitlementsLoaded|"
    r"EventReadyForExternalActions|ownedGameProduct",
    re.I,
)

REDACTIONS = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"), r"\1<REDACTED>"),
    (
        re.compile(
            r"(?i)([?&](?:access_token|refresh_token|id_token|code|code_verifier|"
            r"code_challenge|nonce|pc_sign|state|client_secret|remid|sid)=)[^&\s]+"
        ),
        r"\1<REDACTED>",
    ),
    (
        re.compile(
            r"(?i)(\b(?:access_token|refresh_token|id_token|code|code_verifier|"
            r"code_challenge|nonce|pc_sign|state|client_secret|remid|sid|machineId|"
            r"sessionId|userId|personaId)\s*[=:]\s*)[^&\s,;\]}]+"
        ),
        r"\1<REDACTED>",
    ),
    (
        re.compile(
            r'(?i)("(?:value|machineId|remid|sid|sessionId|userId|personaId|'
            r'valu|nuchash|playerId|visit_id|xRequestId|'
            r'access_token|refresh_token|id_token|code|code_verifier|code_challenge|'
            r'nonce|pc_sign|state|client_secret)"\s*:\s*")[^"]+(" )?'
        ),
        r"\1<REDACTED>\2",
    ),
    (re.compile(r"(?i)(\bvalue=\[).*?(\](?:,|\]))"), r"\1<REDACTED>\2"),
    (
        re.compile(r"(?i)(\b(?:nuchash|playerId|visit_id|xRequestId)\s*[=:]\s*)[^&\s,;\]}]+"),
        r"\1<REDACTED>",
    ),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){1,2}\b"), "<JWT_REDACTED>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL_REDACTED>"),
    (re.compile(r"\b\d{12,}\b"), "<ID_REDACTED>"),
    (re.compile(r"(?i)C:\\Users\\[^\\\s]+"), r"C:\\Users\\<USER>"),
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest().upper()


def redact(line: str) -> str:
    for pattern, replacement in REDACTIONS:
        line = pattern.sub(replacement, line)
    return line.rstrip("\r\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--date-prefix", help="Keep only lines containing this ISO date")
    parser.add_argument("--after", help="Keep records at or after this ISO timestamp")
    parser.add_argument("--before", help="Keep records before this ISO timestamp")
    args = parser.parse_args()

    result: dict[str, object] = {
        "schema": 1,
        "date_filter": args.date_prefix,
        "sources": [],
        "auth": [],
        "library": [],
    }
    for supplied in args.logs:
        source = supplied.resolve()
        if not source.is_file():
            continue
        display_source = redact(str(source))
        result["sources"].append(
            {"path": display_source, "size": source.stat().st_size, "sha256": digest(source)}
        )
        with source.open("r", encoding="utf-8", errors="replace") as stream:
            for line_number, line in enumerate(stream, 1):
                if args.date_prefix and args.date_prefix not in line:
                    continue
                timestamp_match = re.search(r"\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)\]", line)
                timestamp = timestamp_match.group(1) if timestamp_match else None
                if args.after and (timestamp is None or timestamp < args.after):
                    continue
                if args.before and (timestamp is None or timestamp >= args.before):
                    continue
                if AUTH.search(line):
                    result["auth"].append(
                        {"source": display_source, "line": line_number, "text": redact(line)}
                    )
                if LIBRARY.search(line):
                    result["library"].append(
                        {"source": display_source, "line": line_number, "text": redact(line)}
                    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"wrote {args.output}: {len(result['auth'])} auth and "
        f"{len(result['library'])} library records"
    )


if __name__ == "__main__":
    main()
