"""The BFN-tested LSX handshake, version-3 codec, and startup reply adapter."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .lsx_startup import startup_reply


_LSX_TEST_KEY = bytes(range(16))
_BFN_LSX_CONTENT_IDS = frozenset({"Origin.OFR.50.0004873", "194814"})


def _encrypt_challenge_value(value: str) -> str:
    raw = value.encode("ascii")
    padding = 16 - len(raw) % 16
    encryptor = Cipher(algorithms.AES(_LSX_TEST_KEY), modes.ECB()).encryptor()
    return (encryptor.update(raw + bytes([padding]) * padding) + encryptor.finalize()).hex()


def _decrypt_challenge_value(value: str) -> str | None:
    try:
        raw = bytes.fromhex(value)
        decryptor = Cipher(algorithms.AES(_LSX_TEST_KEY), modes.ECB()).decryptor()
        plain = decryptor.update(raw) + decryptor.finalize()
        padding = plain[-1]
        if not 1 <= padding <= 16 or plain[-padding:] != bytes([padding]) * padding:
            return None
        return plain[:-padding].decode("ascii")
    except (ValueError, IndexError, UnicodeDecodeError):
        return None


def _msvc_rand(seed: int) -> tuple[int, int]:
    next_seed = (seed * 214013 + 2531011) & 0xFFFFFFFF
    return next_seed, (next_seed >> 16) & 0x7FFF


def _codec_key(challenge_response: str) -> bytes:
    seed = 7
    seed, initial = _msvc_rand(seed)
    codec_seed = (ord(challenge_response[0]) << 8) + ord(challenge_response[1])
    seed = (codec_seed + initial) & 0xFFFFFFFF
    result = bytearray()
    for _ in range(16):
        seed, value = _msvc_rand(seed)
        result.append(value & 0xFF)
    return bytes(result)


def _encrypt_packet(packet: bytes, key: bytes) -> bytes:
    padding = 16 - len(packet) % 16
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return (encryptor.update(packet + bytes([padding]) * padding) + encryptor.finalize()).hex().encode("ascii") + b"\0"


def _decrypt_packet(packet: bytes, key: bytes) -> bytes | None:
    try:
        raw = bytes.fromhex(packet.decode("ascii"))
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        plain = decryptor.update(raw) + decryptor.finalize()
        padding = plain[-1]
        if not 1 <= padding <= 16 or plain[-padding:] != bytes([padding]) * padding:
            return None
        return plain[:-padding]
    except (ValueError, IndexError, UnicodeDecodeError):
        return None


def challenge_checks(
    response: ET.Element, expected_challenge: str | None,
    *, content_ids: frozenset[str] = _BFN_LSX_CONTENT_IDS,
) -> dict[str, bool]:
    identities = [child.text for child in response if child.tag == "ContentId"]
    return {
        "aes_proof": expected_challenge is not None and _decrypt_challenge_value(
            response.get("response", "")
        ) == expected_challenge,
        "client_key_shape": re.fullmatch(r"[0-9a-fA-F]{32}", response.get("key", "")) is not None,
        "title_identity": len(identities) == 1 and identities[0] in content_ids,
    }


def sdk_startup_reply(
    request: ET.Element, snapshot: dict, *, disable_overlay: bool = False,
    content_id: str = "194814",
) -> bytes | None:
    response = startup_reply(request, snapshot, content_id=content_id)
    if response is None or not disable_overlay:
        return response
    if request[0].tag != "GetSetting" or request[0].get("SettingId") not in (
        "IS_IGO_ENABLED", "IS_IGO_AVAILABLE"
    ):
        return response
    root = ET.fromstring(response)
    root[0][0].set("Setting", "false")
    return ET.tostring(root, encoding="utf-8", short_empty_elements=True)
