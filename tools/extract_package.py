#!/usr/bin/env python3
"""Plan or explicitly extract an EA package; does not run touchup."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standalone_launcher.bootstrap import dpapi_unprotect
from standalone_launcher.download import get_download_descriptor
from standalone_launcher.install import adopt_existing_selection, extract_selection
from standalone_launcher.library import GraphQlClient
from standalone_launcher.login import load_tokens_dpapi, refresh_saved_tokens
from standalone_launcher.manifest import build_install_selection, parse_dip_manifest
from standalone_launcher.remote_zip import HttpRangeFile, read_dip_manifest


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def existing_parent(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise RuntimeError("destination has no existing parent volume")
        candidate = parent
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run by default. --execute streams selected ZIP entries but does not run touchup."
    )
    parser.add_argument("offer_id")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--locale", default="en_US")
    parser.add_argument("--required-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--adopt-existing", action="store_true")
    parser.add_argument("--prune-unselected", action="store_true")
    parser.add_argument("--tokens", type=Path, default=Path("private/ea_tokens.dpapi"))
    parser.add_argument("--secrets", type=Path, default=Path("private/ea_bootstrap.dpapi"))
    parser.add_argument("--metadata", type=Path, default=Path("private/package_metadata"))
    parser.add_argument("--block-mib", type=int, default=8)
    parser.add_argument("--parallel-workers", type=int, default=1,
                        help="parallel HTTP ranges for stored files of at least 64 MiB")
    parser.add_argument("--reserve-mib", type=int, default=1024)
    args = parser.parse_args()
    if args.block_mib <= 0 or args.reserve_mib < 0 or args.parallel_workers <= 0:
        parser.error("block size and worker count must be positive; reserve must be non-negative")

    tokens = load_tokens_dpapi(args.tokens)
    client = GraphQlClient(tokens.access_token)
    descriptor = get_download_descriptor(client, args.offer_id)

    def renew_url() -> str:
        nonlocal client
        try:
            renewed = get_download_descriptor(client, args.offer_id)
        except Exception:
            refreshed = refresh_saved_tokens(args.secrets, args.tokens)
            client = GraphQlClient(refreshed.access_token)
            renewed = get_download_descriptor(client, args.offer_id)
        if renewed.archive_size != descriptor.archive_size:
            raise RuntimeError("EA package size changed while extraction was in progress")
        return renewed.url

    remote = HttpRangeFile(
        descriptor.url,
        descriptor.archive_size,
        block_size=args.block_mib * 1024 * 1024,
        max_cached_blocks=2,
        max_total_bytes=descriptor.archive_size + 64 * 1024 * 1024,
        renew_url=renew_url,
    )
    protected = args.metadata / safe_name(args.offer_id) / "installerdata.xml.dpapi"
    if protected.exists():
        manifest_data = dpapi_unprotect(protected.read_bytes())
    else:
        manifest_data = read_dip_manifest(
            descriptor.url, descriptor.archive_size, range_file=remote
        ).data
    manifest = parse_dip_manifest(manifest_data)

    with zipfile.ZipFile(remote) as archive:
        selection = build_install_selection(
            manifest,
            archive.infolist(),
            locale=args.locale,
            required_only=args.required_only,
        )
        summary = selection.summary
        free = shutil.disk_usage(existing_parent(args.destination)).free
        reserve = args.reserve_mib * 1024 * 1024
        report = {
            "offer_id": args.offer_id,
            "title": manifest.titles.get(summary.locale),
            "game_version": manifest.game_version,
            "destination": str(args.destination.resolve()),
            "execute": args.execute,
            "touchup_will_run": False,
            "plan": summary.as_dict(),
            "free_bytes": free,
            "reserve_bytes": reserve,
            "enough_space": free >= summary.selected_installed_bytes + reserve,
        }
        print(json.dumps(report, indent=2, ensure_ascii=True), flush=True)
        if not args.execute:
            return
        if not report["enough_space"]:
            raise RuntimeError("insufficient free space for selected files plus reserve")

        last_update = 0.0

        def progress(name: str, done: int, total: int) -> None:
            nonlocal last_update
            now = time.monotonic()
            if done == total or now - last_update >= 2:
                percent = 100.0 if not total else done * 100.0 / total
                print(f"[{percent:6.2f}%] {name}", file=sys.stderr, flush=True)
                last_update = now

        if args.adopt_existing:
            adopted = adopt_existing_selection(
                selection.entries,
                args.destination,
                locale=summary.locale,
                game_version=manifest.game_version,
                archive_entries=archive.infolist(),
                prune_unselected=args.prune_unselected,
            )
            print(json.dumps({"adoption": adopted.__dict__}, indent=2), flush=True)

        result = extract_selection(
            archive,
            selection.entries,
            args.destination,
            locale=summary.locale,
            game_version=manifest.game_version,
            parallel_stored_workers=args.parallel_workers,
            progress=progress,
        )
    print(
        json.dumps(
            {
                "extracted_files": result.extracted_files,
                "skipped_files": result.skipped_files,
                "written_bytes": result.written_bytes,
                "completed_files": result.completed_files,
                "range_requests": remote.request_count,
                "bytes_fetched": remote.bytes_fetched,
                "touchup_run": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
