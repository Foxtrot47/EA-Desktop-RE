#!/usr/bin/env python3
"""Dry-run an EA DiP install using a live archive central directory."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standalone_launcher.bootstrap import dpapi_unprotect
from standalone_launcher.download import get_download_descriptor
from standalone_launcher.library import GraphQlClient
from standalone_launcher.login import load_tokens_dpapi
from standalone_launcher.manifest import parse_dip_manifest, plan_install
from standalone_launcher.remote_zip import HttpRangeFile, read_dip_manifest


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calculate a locale/chunk install plan without writing game files."
    )
    parser.add_argument("offer_id")
    parser.add_argument("--locale", default="en_US")
    parser.add_argument("--required-only", action="store_true")
    parser.add_argument("--tokens", type=Path, default=Path("private/ea_tokens.dpapi"))
    parser.add_argument("--metadata", type=Path, default=Path("private/package_metadata"))
    parser.add_argument("--max-range-mib", type=int, default=64)
    args = parser.parse_args()

    tokens = load_tokens_dpapi(args.tokens)
    descriptor = get_download_descriptor(GraphQlClient(tokens.access_token), args.offer_id)
    remote = HttpRangeFile(
        descriptor.url,
        descriptor.archive_size,
        max_total_bytes=args.max_range_mib * 1024 * 1024,
    )

    protected_manifest = (
        args.metadata / safe_name(args.offer_id) / "installerdata.xml.dpapi"
    )
    if protected_manifest.exists():
        manifest_data = dpapi_unprotect(protected_manifest.read_bytes())
        manifest_source = "protected-cache"
    else:
        manifest_data = read_dip_manifest(
            descriptor.url, descriptor.archive_size, range_file=remote
        ).data
        manifest_source = "remote-archive"
    manifest = parse_dip_manifest(manifest_data)

    with zipfile.ZipFile(remote) as archive:
        plan = plan_install(
            manifest,
            archive.infolist(),
            locale=args.locale,
            required_only=args.required_only,
        )

    result = {
        "schema": 1,
        "offer_id": args.offer_id,
        "game_version": manifest.game_version,
        "title": manifest.titles.get(args.locale),
        "manifest_source": manifest_source,
        "archive_size": descriptor.archive_size,
        "archive_overhead_bytes": descriptor.archive_size
        - sum(
            (
                plan.selected_compressed_bytes,
                plan.omitted_locale_compressed_bytes,
                plan.omitted_recommended_compressed_bytes,
                plan.omitted_patch_compressed_bytes,
            )
        ),
        "plan": plan.as_dict(),
        "progressive_chunk_count": len(manifest.chunks),
        "required_chunk_count": sum(chunk.required for chunk in manifest.chunks),
        "recommended_chunk_count": sum(not chunk.required for chunk in manifest.chunks),
        "range_requests": remote.request_count,
        "bytes_fetched": remote.bytes_fetched,
        "notes": [
            "selected_compressed_bytes is exact ZIP payload size; HTTP/local-header overhead is separate",
            "unassigned files are retained conservatively",
            "required-only is an estimate until EA's progressive scheduler is fully recovered",
        ],
    }
    # For full plans, the residual is archive framing. For required-only plans,
    # it also includes omitted recommendations and is therefore not overhead.
    if args.required_only:
        result.pop("archive_overhead_bytes")
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
