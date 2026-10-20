"""Account-backed LSX replies needed by the BFN SDK startup sequence.

This module handles local SDK metadata only.  It does not mint an EA auth code
or claim that online authentication succeeded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
import xml.etree.ElementTree as ET


CONFIG_FACILITIES = (
    "ACHIEVEMENT", "ACHIEVEMENT_EVENT", "CHAT_EVENT", "INVITE_EVENT",
    "BLOCKED_USERS", "BLOCKED_USER_EVENT", "COMMERCE", "COMMERCE_EVENT",
    "CONTENT", "DOWNLOAD_EVENT", "FRIENDS", "FRIENDS_EVENT", "IGO",
    "IGO_EVENT", "LOGIN_EVENT", "ONLINE_STATUS_EVENT", "PERMISSION",
    "PRESENCE", "PRESENCE_EVENT", "PROFILE_EVENT", "PROGRESSIVE_INSTALLATION",
    "PROGRESSIVE_INSTALLATION_EVENT", "PROFILE", "RESOURCES", "SDK",
    "UTILITY", "GET_USERID", "XMPP",
)


def _true(value: Any) -> str:
    return "true" if bool(value) else "false"


def _game_catalog(snapshot: Mapping[str, Any], content_id: str) -> Mapping[str, Any]:
    return next(
        item for item in snapshot["catalog"]["legacyOffers"]
        if str(item.get("contentId")) == content_id
    )


def _profile(snapshot: Mapping[str, Any]) -> dict[str, str]:
    identity = snapshot["identity"]
    me = identity["me"]
    persona = next(
        item for item in me["personas"] if item.get("namespaceName") == "cem_ea_id"
    )
    geo_country = str(identity.get("requestCountry") or me["country"])
    active_subscription = me.get("highestOrRecentSubscription") or {}
    subscribed = active_subscription.get("status") == "ACTIVE"
    # The local EA trace reports INR for this geo-country.  More mappings need
    # account-backed verification before this is used for other countries.
    currency = {"IN": "INR"}.get(geo_country, "USD")
    return {
        "UserIndex": "0",
        "UserId": str(me["userId"]),
        "PersonaId": str(persona["psd"]),
        "Persona": str(persona["displayName"]),
        "AvatarId": "",
        "Country": str(me["country"]),
        "GeoCountry": geo_country,
        "CommerceCountry": geo_country,
        "CommerceCurrency": currency,
        "IsUnderAge": _true(me.get("isUnderage")),
        "IsSteamSubscriber": _true(any(
            item.get("platform") == "STEAM" and item.get("status") == "ACTIVE"
            for item in me.get("subscriptions", [])
        )),
        "IsSubscriber": _true(subscribed),
        "IsTrialSubscriber": "false",
        "SubscriberLevel": str(active_subscription.get("level") or "0") if subscribed else "0",
        "PlatformDisplayName": "",
        "PlatformUserId": "0",
    }


def startup_reply(
    request: ET.Element, snapshot: Mapping[str, Any], *, content_id: str = "194814"
) -> bytes | None:
    """Return one encrypted-channel LSX response body, or None if unsupported."""
    if request.tag != "Request" or request.attrib.get("recipient") != "EbisuSDK":
        return None
    request_id = request.attrib.get("id", "")
    if not request_id.isdecimal() or len(request) != 1:
        return None
    item = request[0]
    catalog = _game_catalog(snapshot, content_id)
    languages = ",".join(catalog.get("softwareLocales") or [])
    version = str((catalog.get("downloads") or [{}])[0].get("gameVersion") or "")
    response_name: str
    attrs: dict[str, str]
    children: tuple[str, ...] = ()
    if item.tag == "GetConfig":
        response_name, attrs = "GetConfigResponse", {}
        children = CONFIG_FACILITIES
    elif item.tag == "GetProfile":
        response_name, attrs = "GetProfileResponse", _profile(snapshot)
    elif item.tag == "GetSetting":
        setting = {
            "IS_IGO_ENABLED": "true",
            "IS_IGO_AVAILABLE": "true",
            "ENVIRONMENT": "production",
        }.get(item.attrib.get("SettingId", ""))
        if setting is None:
            return None
        response_name, attrs = "GetSettingResponse", {"Setting": setting}
    elif item.tag == "GetGameInfo":
        value = {"FREETRIAL": "false", "LANGUAGES": languages}.get(
            item.attrib.get("GameInfoId", "")
        )
        if value is None:
            return None
        response_name, attrs = "GetGameInfoResponse", {"GameInfo": value}
    elif item.tag == "GetAllGameInfo":
        release = str(catalog.get("releaseDate") or "0000-00-00T00:00:00")[:19]
        response_name = "GetAllGameInfoResponse"
        attrs = {
            "UpToDate": "true", "Languages": languages, "FreeTrial": "false",
            "FullGamePurchased": "true", "FullGameReleased": "true",
            "FullGameReleaseDate": release, "Expiration": "0000-00-00T00:00:00",
            "SystemTime": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "HasExpiration": "false", "InstalledVersion": version,
            "InstalledLanguage": "en_US", "AvailableVersion": version,
            "DisplayName": str(catalog.get("displayName") or ""),
            "MaxGroupSize": "16", "EntitlementSource": "EA",
        }
    elif item.tag == "IsProgressiveInstallationAvailable":
        response_name, attrs = "IsProgressiveInstallationAvailableResponse", {
            "ItemId": item.attrib.get("ItemId", ""), "Available": "false"
        }
    elif item.tag == "GetInternetConnectedState":
        # This field is numeric in EA's LSX response, not an XML boolean.
        response_name, attrs = "InternetConnectedState", {"connected": "1"}
    else:
        return None
    root = ET.Element("LSX")
    envelope = ET.SubElement(root, "Response", {"id": request_id, "sender": "EbisuSDK"})
    body = ET.SubElement(envelope, response_name, attrs)
    for facility in children:
        ET.SubElement(body, "Service", {"Name": "EbisuSDK", "Facility": facility})
    return ET.tostring(root, encoding="utf-8", short_empty_elements=True)
