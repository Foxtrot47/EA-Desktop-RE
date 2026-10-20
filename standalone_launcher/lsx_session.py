"""Local BFN SDK session state and authorized game-code handoff.

Presence here describes this launcher session only; it is not published to EA
friends/XMPP. Online game authentication is separate and uses EA-issued codes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
import xml.etree.ElementTree as ET

from .game_auth import BFN_CLIENT_ID, GameAuthError


PRESENCE_FIELDS = (
    "UserId", "Presence", "RichPresence", "Title", "TitleId", "MultiplayerId",
    "Group", "GroupId", "SessionId", "GamePresence",
)


def response_packet(request_id: str, tag: str, attributes: Mapping[str, str]) -> bytes:
    root = ET.Element("LSX")
    envelope = ET.SubElement(root, "Response", {"id": request_id, "sender": "EbisuSDK"})
    ET.SubElement(envelope, tag, dict(attributes))
    return ET.tostring(root, encoding="utf-8", short_empty_elements=True)


class BfnLsxSession:
    def __init__(self, snapshot: Mapping[str, Any], get_auth_code: Callable[[], str]):
        catalog = next(item for item in snapshot["catalog"]["legacyOffers"]
                       if str(item.get("contentId")) == "194814")
        self.user_id = str(snapshot["identity"]["me"]["userId"])
        self.get_auth_code = get_auth_code
        self.presence = dict.fromkeys(PRESENCE_FIELDS, "")
        self.presence.update({
            "UserId": self.user_id, "Presence": "INGAME",
            "Title": str(catalog.get("displayName") or ""),
            "TitleId": str(catalog["offerId"]),
            "MultiplayerId": str(catalog.get("multiplayerId") or ""),
        })
        self.auth_code_requests = 0
        self.auth_code_successes = 0
        self.last_auth_error: str | None = None

    def _auth_reply(self, request_id: str, item: ET.Element) -> bytes:
        if item.get("ClientId") != BFN_CLIENT_ID or item.get("Scope", ""):
            return response_packet(request_id, "ErrorSuccess", {
                "Code": "-1", "Description": "Unsupported game authorization parameters",
            })
        self.auth_code_requests += 1
        try:
            code = self.get_auth_code()
        except GameAuthError as exc:
            self.last_auth_error = str(exc)
            return response_packet(request_id, "ErrorSuccess", {
                "Code": "-1", "Description": "EA game authorization failed",
            })
        if not code:
            raise GameAuthError("EA game authorization returned an empty code")
        self.auth_code_successes += 1
        self.last_auth_error = None
        return response_packet(request_id, "AuthCode", {"value": code})

    def reply(self, request: ET.Element) -> bytes | None:
        if request.tag != "Request" or request.get("recipient") != "EbisuSDK" or len(request) != 1:
            return None
        request_id = request.get("id", "")
        if not request_id.isdecimal():
            return None
        item = request[0]
        if item.tag not in ("GetPresence", "SetPresence", "SetDownloaderUtilization", "GetAuthCode"):
            return None
        if item.get("UserId", "0") not in ("0", self.user_id):
            return response_packet(request_id, "ErrorSuccess", {"Code": "-1", "Description": "Invalid user"})
        handlers = {
            "GetPresence": self._get_presence,
            "SetPresence": self._set_presence,
            "SetDownloaderUtilization": self._downloader,
            "GetAuthCode": self._auth_reply,
        }
        return handlers[item.tag](request_id, item)

    def _get_presence(self, request_id: str, item: ET.Element) -> bytes:
        return response_packet(request_id, "GetPresenceResponse", self.presence)

    def _set_presence(self, request_id: str, item: ET.Element) -> bytes:
        for field in ("Presence", "RichPresence", "SessionId", "GamePresence"):
            if field in item.attrib:
                self.presence[field] = item.attrib[field]
        return response_packet(request_id, "ErrorSuccess", {"Code": "0", "Description": ""})

    def _downloader(self, request_id: str, item: ET.Element) -> bytes:
        # Same unsupported-operation code seen in the normal-launch oracle.
        return response_packet(request_id, "ErrorSuccess", {
            "Code": "-1576467979", "Description": "Downloader utilization is unavailable",
        })
