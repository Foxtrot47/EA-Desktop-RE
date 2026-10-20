"""Verify legacy OOA license signatures using EA Desktop's public DSA key.

The DSA parameters in ooa_public_key.json are public verification material
extracted from EADesktop.exe 13.809.0.6322. License bodies remain opaque here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class DsaPublicKey:
    p: int
    q: int
    g: int
    y: int


@lru_cache(maxsize=1)
def ooa_public_key() -> DsaPublicKey:
    path = Path(__file__).with_name("ooa_public_key.json")
    values = json.loads(path.read_text(encoding="utf-8"))
    return DsaPublicKey(*(int(values[name], 16) for name in ("p", "q", "g", "y")))


def _parse_dsa_der(signature: bytes) -> tuple[int, int] | None:
    """Read the two positive DER INTEGERs from a short DSA signature."""
    if len(signature) < 8 or signature[0] != 0x30:
        return None
    length = signature[1]
    if length & 0x80 or length + 2 != len(signature):
        return None
    offset = 2
    numbers: list[int] = []
    for _ in range(2):
        if offset + 2 > len(signature) or signature[offset] != 0x02:
            return None
        size = signature[offset + 1]
        offset += 2
        if size == 0 or offset + size > len(signature):
            return None
        integer = signature[offset : offset + size]
        if integer[0] & 0x80:
            return None
        if size > 1 and integer[0] == 0 and not integer[1] & 0x80:
            return None
        numbers.append(int.from_bytes(integer, "big"))
        offset += size
    if offset != len(signature):
        return None
    return numbers[0], numbers[1]


def verify_ooa_signature(
    body: bytes, signature: bytes, *, public_key: DsaPublicKey | None = None
) -> bool:
    """Match EADesktop's SHA-1 + DSA verification over the binary body."""
    values = _parse_dsa_der(signature)
    if values is None or not body:
        return False
    key = public_key or ooa_public_key()
    r, s = values
    if not 0 < r < key.q or not 0 < s < key.q:
        return False
    try:
        inverse = pow(s, -1, key.q)
    except ValueError:
        return False
    digest = int.from_bytes(hashlib.sha1(body).digest(), "big")
    u1 = digest * inverse % key.q
    u2 = r * inverse % key.q
    check = (pow(key.g, u1, key.p) * pow(key.y, u2, key.p) % key.p) % key.q
    return check == r
