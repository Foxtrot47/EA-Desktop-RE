"""Launch an installed EA title without starting EA Desktop."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standalone_launcher.launch import (
    LaunchError,
    launch_executable,
)
from standalone_launcher.managed_launch import BFN_CONTENT_ID, launch_game
from standalone_launcher.console_trace import finish_console_trace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="game executable or installed game directory")
    parser.add_argument("arguments", nargs="*", help="arguments used with an explicit executable")
    parser.add_argument("--launcher-uid", help="DiP launcher UID when target is an install directory")
    parser.add_argument("--locale", default="en_US", help="launcher-name locale (default: en_US)")
    parser.add_argument("--wait", action="store_true", help="wait for BFN's game session, or the immediate launcher for other titles")
    parser.add_argument("--trace", action="store_true", help="live redacted BFN LSX/launcher-HTTP conversation; implies --wait")
    args = parser.parse_args()

    try:
        if args.target.is_dir():
            if args.arguments:
                parser.error("positional arguments require an executable target")
            launcher, process = launch_game(
                args.target,
                launcher_uid=args.launcher_uid,
                locale=args.locale,
                trace=args.trace,
            )
            mode = "standalone session" if launcher.content_id == BFN_CONTENT_ID else f"launcher {launcher.uid}"
            print(f"Started {launcher.name} ({mode}, PID {process.pid}).")
        else:
            if args.launcher_uid:
                parser.error("--launcher-uid requires an install-directory target")
            if args.trace:
                parser.error("--trace requires an install-directory target")
            process = launch_executable(args.target, args.arguments)
            print(f"Started {args.target.name} (PID {process.pid}).")
        if args.wait or args.trace:
            try:
                return process.wait()
            finally:
                finish_console_trace(process)
        return 0
    except LaunchError as exc:
        print(f"Launch failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if not args.trace:
            raise
        print("Stopped console tracing; the running game session was left intact.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
