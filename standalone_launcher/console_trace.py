"""Opt-in, value-redacted console traces. Never render raw protocol bodies."""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from typing import Mapping
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from .lsx_startup import CONFIG_FACILITIES


REDACTED = "<redacted>"
TRACE_PREFIXES = ("[LSX ", "[HTTP ")
_PUBLIC_VALUES = {
    "sender": {"EALS", "EbisuSDK"}, "recipient": {"EALS", "EbisuSDK"},
    "build": {"release"}, "name": {"EbisuSDK"}, "facility": set(CONFIG_FACILITIES),
    "settingid": {"IS_IGO_ENABLED", "IS_IGO_AVAILABLE", "ENVIRONMENT"},
    "gameinfoid": {"FREETRIAL", "LANGUAGES"},
    "setting": {"true", "false", "production"}, "gameinfo": {"true", "false"},
    "presence": {"ONLINE", "OFFLINE", "INGAME", "AWAY", "DND", "UNKNOWN"},
    "clientid": {"PVZGW3-PC-SERVER-BLAZE"}, "client_id": {"PVZGW3-PC-SERVER-BLAZE", "JUNO_PC_CLIENT"},
    "grant_type": {"refresh_token", "authorization_code"}, "release_type": {"prod"},
    "response_type": {"code"}, "token_type": {"Bearer"}, "scope": {""},
    "connected": {"0", "1"}, "contentid": {"194814", "Origin.OFR.50.0004873"},
}
_NUMERIC_FIELDS = {"id", "index", "userindex", "code", "expires_in", "maxgroupsize", "utilization"}
_BOOLEAN_FIELDS = {
    "uptodate", "freetrial", "fullgamepurchased", "fullgamereleased", "hasexpiration",
    "available",
}


def _safe_value(name: str, value) -> str:
    key = name.casefold()
    text = str(value) if isinstance(value, (str, int, float, bool)) else ""
    if text in _PUBLIC_VALUES.get(key, ()):
        return text
    if key in _NUMERIC_FIELDS and re.fullmatch(r"-?[0-9]{1,12}", text):
        return text
    if key in _BOOLEAN_FIELDS and text in ("true", "false"):
        return text
    if key == "version" and re.fullmatch(r"[0-9]+(?:[.,][0-9]+){0,4}", text):
        return text
    if key in ("language", "languages", "installedlanguage") and re.fullmatch(r"[a-z]{2}_[A-Z]{2}(?:,[a-z]{2}_[A-Z]{2})*", text):
        return text
    return REDACTED


def _xml_value(tag: str, name: str, value) -> str:
    if name.casefold() == "id" and tag not in ("Request", "Response"):
        return REDACTED
    if name.casefold() == "code" and tag != "ErrorSuccess":
        return REDACTED
    return _safe_value(name, value)


def _redacted_xml(element: ET.Element, sensitive: bool = False) -> ET.Element:
    # AuthCode.value, profile IDs/names, challenge material, presence strings,
    # unknown fields and all unexpected text default to redaction.
    sensitive = sensitive or element.tag == "AuthCode"
    attrs = {key: REDACTED if sensitive else _xml_value(element.tag, key, value) for key, value in element.attrib.items()}
    result = ET.Element(element.tag, attrs)
    if element.text and element.text.strip():
        result.text = REDACTED if sensitive else _xml_value(element.tag, element.tag, element.text)
    for child in element:
        result.append(_redacted_xml(child, sensitive))
    return result


def _redacted_mapping(values: Mapping | None):
    if values is None:
        return None
    if not isinstance(values, Mapping):
        return REDACTED
    public_fields = {"client_id", "release_type", "response_type", "grant_type", "token_type", "expires_in", "scope"}
    return {str(key): _safe_value(str(key), value) if str(key).casefold() in public_fields else REDACTED for key, value in values.items()}


def _endpoint(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return REDACTED
    if parsed.hostname == "accounts.ea.com" and parsed.path in ("/connect/auth", "/connect/token"):
        return "https://accounts.ea.com" + parsed.path
    return REDACTED


class ConsoleTrace:
    def __init__(self, enabled: bool = False, *, stream=None):
        self.enabled = enabled
        self.stream = sys.stderr if stream is None else stream
        self.started = time.monotonic()

    def _emit(self, family: str, direction: str, message: str) -> None:
        if not self.enabled:
            return
        elapsed = time.monotonic() - self.started
        try:
            print(f"[{family} {elapsed:8.3f}s {direction}] {message}", file=self.stream, flush=True)
        except (OSError, ValueError):
            # Closing a console must not alter the running game's protocol.
            self.enabled = False

    def lsx(self, direction: str, packet: bytes) -> None:
        if not self.enabled:
            return
        try:
            root = ET.fromstring(packet.rstrip(b"\0"))
        except ET.ParseError:
            self._emit("LSX", direction, "<unparsed message; body omitted>")
            return
        text = ET.tostring(_redacted_xml(root), encoding="unicode", short_empty_elements=True)
        self._emit("LSX", direction, text)

    def http_request(self, method: str, url: str, *, fields: Mapping | None = None) -> None:
        if not self.enabled:
            return
        body = json.dumps(_redacted_mapping(fields), ensure_ascii=True)
        self._emit("HTTP", "->", f"{method} {_endpoint(url)} fields={body}")

    def http_response(self, method: str, url: str, status, *, fields: Mapping | None = None, headers: Mapping | None = None) -> None:
        if not self.enabled:
            return
        body = json.dumps({"fields": _redacted_mapping(fields), "headers": _redacted_mapping(headers)}, ensure_ascii=True)
        self._emit("HTTP", "<-", f"{method} {_endpoint(url)} status={status} {body}")

    def http_failure(self, method: str, url: str) -> None:
        self._emit("HTTP", "<-", f"{method} {_endpoint(url)} transport failed; details omitted")


def forward_trace_lines(source, destination) -> None:
    """Forward only the trace channel, continuing to drain if a console closes."""
    sink = destination
    try:
        for line in source:
            if not line.startswith(TRACE_PREFIXES) or sink is None:
                continue
            try:
                sink.write(line)
                sink.flush()
            except (OSError, ValueError):
                sink = None
    finally:
        source.close()


def start_trace_forwarder(source, destination=None) -> threading.Thread:
    thread = threading.Thread(
        target=forward_trace_lines, args=(source, sys.stderr if destination is None else destination), daemon=True
    )
    thread.start()
    return thread


def finish_console_trace(process) -> None:
    thread = getattr(process, "_ea_trace_thread", None)
    if thread is not None:
        thread.join(timeout=2)
