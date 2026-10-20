#!/usr/bin/env python3
"""Fetch and install a signed OOA license for one active EA offer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standalone_launcher.license import LicenseError
from standalone_launcher.license_service import refresh_owned_license


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("offer_id", help="active legacy offer ID from the standalone library")
    parser.add_argument("--refresh-token", action="store_true", help="refresh the saved OAuth session first")
    args = parser.parse_args()
    try:
        result = refresh_owned_license(args.offer_id, refresh_token=args.refresh_token)
    except (KeyError, OSError, ValueError, LicenseError) as exc:
        parser.exit(1, f"License refresh failed: {exc}\n")
    print(
        f"Installed EA-signed license for {result.offer_id} (content ID {result.content_id}) "
        f"at {result.path}; protected previous-license backup: {'yes' if result.backup else 'not needed'}"
    )


if __name__ == "__main__":
    main()
