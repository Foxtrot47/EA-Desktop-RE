#!/usr/bin/env python3
"""Extract this pinned EA build's auth material directly into DPAPI storage."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from standalone_launcher.bootstrap import extract_secrets, load_dpapi, save_dpapi


def short_fingerprint(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()[:12]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    secrets = extract_secrets(args.binary)
    save_dpapi(args.output, secrets)
    verified = load_dpapi(args.output)
    if verified != secrets:
        raise RuntimeError("DPAPI round-trip verification failed")
    print(
        {
            "source_sha256": secrets.source_sha256,
            "dpapi_file": str(args.output.resolve()),
            "production_key_count": len(secrets.production_pc_sign_keys),
            "production_key_fingerprints": [short_fingerprint(value) for value in secrets.production_pc_sign_keys],
            "nonproduction_key_count": len(secrets.nonproduction_pc_sign_keys),
            "client_secret_environments": sorted(secrets.client_secret_by_environment),
            "client_secret_lengths": {key: len(value) for key, value in secrets.client_secret_by_environment.items()},
        }
    )


if __name__ == "__main__":
    main()
