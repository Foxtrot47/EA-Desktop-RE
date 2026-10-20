"""Account-authorized SDK license replies using EA-issued GameToken values."""
from __future__ import annotations

import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .license import LicenseError, fetch_signed_license, install_signed_license, owned_content_id
from .login import load_tokens_dpapi, refresh_saved_tokens
from .machine import collect_local_machine_fields
from .ooa_verify import verify_ooa_signature

_EA_BINARY_SHA256 = "6ec60c4d45a0a6cde311a0dd26c529026e0384e7f05bc9877d7a56ac53b1840b"
# Native OOA decoder data location in the exact verified EA binary. Never log its bytes.
_DECODER_OFFSET = 23254200


def server_game_token(signed, binary: Path, content_id: str, user_id: str, machine_hash: str) -> str:
    if not verify_ooa_signature(signed.body, signed.signature):
        raise LicenseError("EA response signature verification failed")
    image = binary.read_bytes()
    if hashlib.sha256(image).hexdigest() != _EA_BINARY_SHA256:
        raise LicenseError("unrecognized EA license decoder build")
    key = image[_DECODER_OFFSET:_DECODER_OFFSET + 16]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).decryptor()
    plain = decryptor.update(signed.body) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    try:
        document = ET.fromstring(unpadder.update(plain) + unpadder.finalize())
    except (ValueError, ET.ParseError):
        raise LicenseError("EA license body could not be parsed") from None
    fields = {}
    for node in document.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag in {"ContentId", "UserId", "MachineHash", "GameToken"}:
            if tag in fields:
                raise LicenseError("EA license contains duplicate binding fields")
            fields[tag] = node.text or ""
    if any(fields.get(tag) != value for tag, value in (
        ("ContentId", content_id), ("UserId", user_id), ("MachineHash", machine_hash)
    )):
        raise LicenseError("EA license binding does not match the authorized request")
    token = fields.get("GameToken", "")
    if not token:
        raise LicenseError("EA license does not contain a game token")
    return token


class OwnedLicenseSession:
    """One fresh SDK ticket exchange per launch; no values leave memory or signed .dlf."""

    def __init__(self, snapshot: dict, offer_id: str, root: Path):
        self.content_id = owned_content_id(snapshot, offer_id)
        if self.content_id != "1035049":
            raise LicenseError("SDK license exchange is currently scoped to Unravel Two")
        self.user_id = str(snapshot["identity"]["me"]["userId"])
        self.root = root
        self.requests = 0
        self.successes = 0
        self.last_error = None
        self.request_shape = None
        self._ticket = None
        self._license = None

    def _exchange(self, ticket: str) -> str:
        if self.requests:
            raise LicenseError("a different SDK ticket requires a new diagnostic session")
        self.requests += 1
        machine = collect_local_machine_fields().fingerprint_sha1_hex
        tokens_path = self.root / "private/ea_tokens.dpapi"
        tokens = load_tokens_dpapi(tokens_path)
        try:
            signed = fetch_signed_license(self.content_id, machine, self.user_id,
                                          tokens.access_token, request_token=ticket)
        except LicenseError as exc:
            if "HTTP 401" not in str(exc):
                raise
            tokens = refresh_saved_tokens(self.root / "private/ea_bootstrap.dpapi", tokens_path)
            signed = fetch_signed_license(self.content_id, machine, self.user_id,
                                          tokens.access_token, request_token=ticket)
        token = server_game_token(signed, self.root / "artifacts/EADesktop.exe",
                                  self.content_id, self.user_id, machine)
        install_signed_license(signed)
        self.successes += 1
        return token

    def reply(self, request: ET.Element) -> bytes | None:
        if request.tag != "Request" or request.get("recipient") != "EbisuSDK" or len(request) != 1:
            return None
        item = request[0]
        if item.tag != "RequestLicense" or not request.get("id", "").isdecimal():
            return None
        ticket = item.get("RequestTicket", "")
        self.request_shape = {"attributes": sorted(item.attrib), "ticket_length": len(ticket),
                              "own_user": item.get("UserId") == self.user_id,
                              "ticket_engine": item.get("TicketEngine") if item.get("TicketEngine", "").isdecimal() else None}
        try:
            if item.get("UserId") != self.user_id or not ticket:
                raise LicenseError("SDK license request identity or ticket is invalid")
            if ticket != self._ticket:
                self._license = self._exchange(ticket)
                self._ticket = ticket
            envelope = ET.Element("LSX")
            response = ET.SubElement(envelope, "Response", {"id": request.get("id"), "sender": "EbisuSDK"})
            ET.SubElement(response, "RequestLicenseResponse", {"License": self._license})
            return ET.tostring(envelope, encoding="utf-8", short_empty_elements=True)
        except LicenseError as exc:
            self.last_error = str(exc)
            return None
        except Exception as exc:
            self.last_error = type(exc).__name__
            return None
