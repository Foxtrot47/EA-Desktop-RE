#!/usr/bin/env python3
"""Open EA login and save the resulting OAuth tokens under Windows DPAPI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standalone_launcher.login import interactive_login, load_tokens_dpapi


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secrets", type=Path, default=Path("private/ea_bootstrap.dpapi"))
    parser.add_argument(
        "--host",
        type=Path,
        default=Path("auth_host/bin/Release/net8.0-windows/EaStandalone.AuthHost.dll"),
    )
    parser.add_argument("--tokens", type=Path, default=Path("private/ea_tokens.dpapi"))
    args = parser.parse_args()
    tokens = interactive_login(args.secrets, args.host, args.tokens)
    verified = load_tokens_dpapi(args.tokens)
    if verified != tokens:
        raise RuntimeError("token DPAPI round-trip failed")
    print(
        {
            "login": "succeeded",
            "token_store": str(args.tokens.resolve()),
            "token_type": tokens.token_type,
            "expires_in": tokens.expires_in,
            "refresh_token_present": tokens.refresh_token is not None,
            "id_token_present": tokens.id_token is not None,
            "scope_present": tokens.scope is not None,
        }
    )


if __name__ == "__main__":
    main()
