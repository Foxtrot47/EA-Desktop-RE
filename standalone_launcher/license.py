"""Acquire EA-signed legacy OOA licenses for owned catalog offers.

The server supplies both the opaque license body and its signature. This
module only reproduces EA Desktop's request and local .dlf container format.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib import error, parse, request

from .bootstrap import dpapi_protect, dpapi_unprotect


OOA_LICENSE_ENDPOINT = "https://gateway.ea.com/proxy/access/licenses"
OOA_USER_AGENT = "OOA/5.02.21"
_SAFE_CONTENT_ID = re.compile(r"[A-Za-z0-9._-]+\Z")
_MACHINE_HASH = re.compile(r"[0-9a-f]{20,40}\Z")
_BINDINGS_FILE = Path(__file__).resolve().parents[1] / "private" / "ooa_machine_bindings.dpapi"


class LicenseError(RuntimeError):
    pass


def save_machine_binding(
    content_id: str, machine_hash: str, *, path: Path = _BINDINGS_FILE
) -> None:
    """Keep a confirmed, title-specific binding under the current user's DPAPI."""
    if not _SAFE_CONTENT_ID.fullmatch(content_id) or not _MACHINE_HASH.fullmatch(machine_hash):
        raise LicenseError("invalid content ID or machine binding")
    bindings: dict[str, str] = {}
    if path.exists():
        loaded = json.loads(dpapi_unprotect(path.read_bytes()))
        if loaded.get("version") != 1 or not isinstance(loaded.get("bindings"), dict):
            raise LicenseError("machine binding store is malformed")
        bindings = loaded["bindings"]
    bindings[content_id] = machine_hash
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"version": 1, "bindings": bindings}, separators=(",", ":")).encode()
    protected = dpapi_protect(payload, "EA standalone launcher OOA machine bindings")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".ooa-binding-", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(protected)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_machine_binding(content_id: str, *, path: Path = _BINDINGS_FILE) -> str:
    if not _SAFE_CONTENT_ID.fullmatch(content_id):
        raise LicenseError("invalid content ID")
    if not path.exists():
        raise LicenseError("no confirmed OOA machine binding has been saved")
    loaded = json.loads(dpapi_unprotect(path.read_bytes()))
    if loaded.get("version") != 1 or not isinstance(loaded.get("bindings"), dict):
        raise LicenseError("machine binding store is malformed")
    binding = loaded["bindings"].get(content_id)
    if not isinstance(binding, str) or not _MACHINE_HASH.fullmatch(binding):
        raise LicenseError(f"no confirmed OOA machine binding for content ID {content_id}")
    return binding


@dataclass(frozen=True)
class SignedLicense:
    content_id: str
    body: bytes
    signature: bytes

    def dlf_bytes(self) -> bytes:
        if not self.body or len(self.body) > 65536:
            raise LicenseError("license response body has an invalid length")
        if not self.signature or len(self.signature) > 64:
            raise LicenseError("license response signature has an invalid length")
        return self.signature.ljust(64, b"\0") + b"\0" + self.body


def owned_content_id(snapshot: Mapping[str, Any], offer_id: str) -> str:
    """Resolve an active entitlement through the legacy catalog."""
    entitlements = snapshot.get("entitlements", [])
    active = any(
        isinstance(item, Mapping)
        and item.get("productId") == offer_id
        and item.get("status") == "ACTIVE"
        for item in entitlements
    )
    if not active:
        raise LicenseError(f"no active entitlement for offer {offer_id}")
    catalog = snapshot.get("catalog", {})
    offers = catalog.get("legacyOffers", []) if isinstance(catalog, Mapping) else []
    match = next(
        (item for item in offers if isinstance(item, Mapping) and item.get("offerId") == offer_id),
        None,
    )
    content_id = match.get("contentId") if match else None
    if not isinstance(content_id, str) or not _SAFE_CONTENT_ID.fullmatch(content_id):
        raise LicenseError(f"no usable legacy content ID for offer {offer_id}")
    return content_id


def license_path(content_id: str, root: Path | None = None) -> Path:
    if not _SAFE_CONTENT_ID.fullmatch(content_id):
        raise LicenseError("invalid content ID")
    if root is None:
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        root = program_data / "Electronic Arts" / "EA Services" / "License"
    return root / f"{content_id}.dlf"


def _license_query(content_id: str, machine_hash: str, user_id: str, request_token: str | None) -> str:
    parameters = [("contentId", content_id), ("machineHash", machine_hash), ("userId", user_id)]
    if request_token is not None:
        if not request_token or len(request_token) > 4000 or any(ord(char) < 32 for char in request_token):
            raise LicenseError("invalid OOA game request token")
        parameters.append(("requestToken", request_token))
    return parse.urlencode(parameters)


def fetch_signed_license(
    content_id: str,
    machine_hash: str,
    user_id: str,
    access_token: str,
    *,
    endpoint: str = OOA_LICENSE_ENDPOINT,
    timeout: int = 30,
    request_token: str | None = None,
) -> SignedLicense:
    if not _SAFE_CONTENT_ID.fullmatch(content_id):
        raise LicenseError("invalid content ID")
    if not _MACHINE_HASH.fullmatch(machine_hash):
        raise LicenseError("invalid OOA machine hash")
    if not user_id or not access_token:
        raise LicenseError("account ID and access token are required")
    query = _license_query(content_id, machine_hash, user_id, request_token)
    http_request = request.Request(
        f"{endpoint}?{query}",
        headers={
            "User-Agent": OOA_USER_AGENT,
            "Authorization": f"Bearer {access_token}",
        },
        method="GET",
    )
    tls = ssl.create_default_context()
    tls.maximum_version = ssl.TLSVersion.TLSv1_2
    try:
        with request.urlopen(http_request, timeout=timeout, context=tls) as response:
            body = response.read(65537)
            signature_header = response.headers.get("X-Signature", "")
    except error.HTTPError as exc:
        raise LicenseError(f"EA license request failed with HTTP {exc.code}") from None
    except (error.URLError, TimeoutError) as exc:
        raise LicenseError(f"EA license request failed: {type(exc).__name__}") from None
    if not signature_header or len(signature_header) > 128:
        raise LicenseError("EA license response is missing its signature")
    try:
        signature = base64.b64decode(signature_header, validate=True)
    except (binascii.Error, ValueError):
        raise LicenseError("EA license response signature is malformed") from None
    result = SignedLicense(content_id, body, signature)
    result.dlf_bytes()  # Check lengths before any caller can persist the response.
    return result


def install_signed_license(
    signed: SignedLicense,
    *,
    destination: Path | None = None,
    backup_directory: Path | None = None,
) -> tuple[Path, Path | None]:
    """Atomically install a server-issued license after protecting any old one."""
    target = destination or license_path(signed.content_id)
    if target.name != f"{signed.content_id}.dlf":
        raise LicenseError("license destination name does not match content ID")
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if target.exists():
        original = target.read_bytes()
        backup_root = backup_directory or Path(__file__).resolve().parents[1] / "private" / "license_backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(original).hexdigest()[:16]
        backup = backup_root / f"{signed.content_id}-{digest}.dlf.dpapi"
        if not backup.exists():
            backup.write_bytes(dpapi_protect(original, "EA standalone launcher license backup"))
    payload = signed.dlf_bytes()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{signed.content_id}-", suffix=".tmp", dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target, backup
