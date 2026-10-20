"""Account-aware acquisition of EA-signed legacy OOA licenses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .library import load_snapshot_dpapi
from .license import (
    LicenseError,
    fetch_signed_license,
    install_signed_license,
    load_machine_binding,
    owned_content_id,
)
from .login import load_tokens_dpapi, refresh_saved_tokens
from .machine import collect_local_machine_fields
from .ooa_machine import collect_legacy_ooa_machine_hash
from .ooa_verify import verify_ooa_signature


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LicenseRefreshResult:
    offer_id: str
    content_id: str
    path: Path
    backup: Path | None


def refresh_owned_license(
    offer_id: str, *, root: Path = ROOT, refresh_token: bool = False
) -> LicenseRefreshResult:
    """Renew one active offer without EA Desktop or its background service."""
    snapshot = load_snapshot_dpapi(root / "private" / "ea_library.dpapi")
    content_id = owned_content_id(snapshot, offer_id)
    user_id = str(snapshot["identity"]["me"]["userId"])
    if content_id == "1019521":
        machine_hash = collect_legacy_ooa_machine_hash()
    elif content_id == "194814":
        # Battle for Neighborville's Activation64 uses mode 4 and fixed-width
        # SHA-1 formatting for its locally calculated machine binding.
        machine_hash = collect_local_machine_fields().fingerprint_sha1_hex
    else:
        machine_hash = load_machine_binding(content_id)
    tokens = (
        refresh_saved_tokens(root / "private" / "ea_bootstrap.dpapi", root / "private" / "ea_tokens.dpapi")
        if refresh_token
        else load_tokens_dpapi(root / "private" / "ea_tokens.dpapi")
    )
    try:
        signed = fetch_signed_license(content_id, machine_hash, user_id, tokens.access_token)
    except LicenseError as exc:
        if refresh_token or "HTTP 401" not in str(exc):
            raise
        tokens = refresh_saved_tokens(root / "private" / "ea_bootstrap.dpapi", root / "private" / "ea_tokens.dpapi")
        signed = fetch_signed_license(content_id, machine_hash, user_id, tokens.access_token)
    if not verify_ooa_signature(signed.body, signed.signature):
        raise LicenseError("EA license response failed local signature verification")
    path, backup = install_signed_license(signed)
    return LicenseRefreshResult(offer_id, content_id, path, backup)
