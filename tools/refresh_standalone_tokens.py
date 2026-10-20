#!/usr/bin/env python3
"""Refresh the DPAPI-protected standalone OAuth session."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standalone_launcher.login import load_tokens_dpapi, refresh_saved_tokens


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secrets", type=Path, default=Path("private/ea_bootstrap.dpapi"))
    parser.add_argument("--tokens", type=Path, default=Path("private/ea_tokens.dpapi"))
    args = parser.parse_args()
    tokens = refresh_saved_tokens(args.secrets, args.tokens)
    if load_tokens_dpapi(args.tokens) != tokens:
        raise RuntimeError("refreshed-token DPAPI round-trip failed")
    print(
        {
            "refresh": "succeeded",
            "token_store": str(args.tokens.resolve()),
            "token_type": tokens.token_type,
            "expires_in": tokens.expires_in,
            "refresh_token_present": tokens.refresh_token is not None,
            "id_token_present": tokens.id_token is not None,
        }
    )


if __name__ == "__main__":
    main()
