"""EA ``pc_sign`` serialization and signing primitives.

Key recovery and machine-field collection are intentionally separate. This
module accepts those values and reproduces the recovered wire format without
depending on any EA process.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import string
from dataclasses import asdict, dataclass
from datetime import datetime


def _base64url_no_padding(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class PcSignPayload:
    """Field schema recovered from EADesktop.exe 13.809.0.6322."""

    mid: str
    bsn: str | None
    msn: str | None
    hsn: str
    mac: str
    gid: int
    ts: str
    av: str = "v1"
    sv: str = "v1"

    def compact_json(self) -> bytes:
        # EADesktop uses nlohmann::json's default ordered object. Its compact
        # serializer emits map keys in lexical order and no insignificant space.
        text = json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return text.encode("utf-8")


def build_pc_sign(payload: PcSignPayload, signing_key: bytes) -> str:
    """Create EA's payload/signature envelope.

    EA signs the ASCII base64url payload segment, not the JSON bytes directly.
    """
    if len(signing_key) != 32:
        raise ValueError("EA pc_sign uses a 32-byte HMAC key")
    body = payload.compact_json()
    encoded_body = _base64url_no_padding(body)
    signature = hmac.new(signing_key, encoded_body.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_body}.{_base64url_no_padding(signature)}"


def format_pc_sign_timestamp(value: datetime) -> str:
    """Format EA's unpadded local application-clock timestamp."""
    milliseconds = value.microsecond // 1000
    return (
        f"{value.year}-{value.month}-{value.day} "
        f"{value.hour}:{value.minute}:{value.second}:{milliseconds}"
    )


def fnv1a_64(value: bytes) -> int:
    """The 64-bit FNV-1a primitive used to derive the ``mid`` field."""
    result = 0xCBF29CE484222325
    for byte in value:
        result = ((result ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return result


def normalize_pc_sign_mac(hyphenated_mac: str) -> str:
    """Convert EA's lowercase ``aa-bb-...`` adapter form to ``$aabb...``."""
    compact = hyphenated_mac.replace("-", "")
    if not compact or any(character not in string.hexdigits for character in compact):
        raise ValueError("MAC must contain hexadecimal octets")
    return "$" + compact.lower()


def derive_mid(machine_fingerprint_hex: str, normalized_mac: str) -> str:
    """Return the decimal FNV-1a hash used for ``mid``.

    The first component is EA's lowercase SHA-1 hex encoding of its mode-4
    legacy machine fingerprint. The second is the ``$aabb...`` MAC form.
    """
    material = (machine_fingerprint_hex + normalized_mac).encode("ascii")
    return str(fnv1a_64(material))
