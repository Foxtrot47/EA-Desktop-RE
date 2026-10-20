#!/usr/bin/env python3
"""Fetch and protect a package's small install metadata, never its payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standalone_launcher.bootstrap import dpapi_protect
from standalone_launcher.download import get_download_descriptor
from standalone_launcher.library import GraphQlClient
from standalone_launcher.login import load_tokens_dpapi
from standalone_launcher.remote_zip import HttpRangeFile, read_dip_manifest, read_named_member


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("offer_id")
    parser.add_argument("--tokens", type=Path, default=Path("private/ea_tokens.dpapi"))
    parser.add_argument("--output", type=Path, default=Path("private/package_metadata"))
    parser.add_argument("--max-range-mib", type=int, default=64)
    args = parser.parse_args()

    tokens = load_tokens_dpapi(args.tokens)
    descriptor = get_download_descriptor(GraphQlClient(tokens.access_token), args.offer_id)
    remote = HttpRangeFile(
        descriptor.url,
        descriptor.archive_size,
        max_total_bytes=args.max_range_mib * 1024 * 1024,
    )
    manifest = read_dip_manifest(descriptor.url, descriptor.archive_size, range_file=remote)
    root = ET.fromstring(manifest.data)
    install_path = root.findtext("./installManifest/filePath")
    install_data = read_named_member(remote, install_path) if install_path else None

    destination = args.output / safe_name(args.offer_id)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "installerdata.xml.dpapi").write_bytes(
        dpapi_protect(manifest.data, f"EA package metadata {args.offer_id} installerdata.xml")
    )
    if install_data is not None:
        (destination / "install-manifest.dpapi").write_bytes(
            dpapi_protect(install_data, f"EA package metadata {args.offer_id} install manifest")
        )
    metadata = {
        "schema": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "offer_id": args.offer_id,
        "archive_size": descriptor.archive_size,
        "archive_entry_count": manifest.archive_entry_count,
        "dip_member": manifest.archive_member,
        "dip_size": len(manifest.data),
        "dip_sha256": hashlib.sha256(manifest.data).hexdigest().upper(),
        "install_manifest_member": install_path,
        "install_manifest_size": len(install_data) if install_data is not None else None,
        "install_manifest_sha256": (
            hashlib.sha256(install_data).hexdigest().upper() if install_data is not None else None
        ),
        "range_requests": remote.request_count,
        "bytes_fetched": remote.bytes_fetched,
    }
    (destination / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
