#!/usr/bin/env python3
"""Observe local LSX connection timing without retaining message contents."""

from __future__ import annotations

import argparse
import re
import secrets
import selectors
import socket
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from standalone_launcher.library import load_snapshot_dpapi
from standalone_launcher.license import owned_content_id
from standalone_launcher.lsx_license import OwnedLicenseSession
from standalone_launcher.lsx_startup import startup_reply
from standalone_launcher.lsx_session import BfnLsxSession
from standalone_launcher.game_auth import fetch_bfn_auth_code
from standalone_launcher.login import refresh_saved_tokens
from standalone_launcher.console_trace import ConsoleTrace
from standalone_launcher.lsx_protocol import (
    _LSX_TEST_KEY, _encrypt_challenge_value, _decrypt_challenge_value,
    _msvc_rand, _codec_key, _encrypt_packet, _decrypt_packet, challenge_checks,
    sdk_startup_reply as diagnostic_startup_reply,
)


_CONFIG_FACILITIES = (
    "ACHIEVEMENT", "ACHIEVEMENT_EVENT", "CHAT_EVENT", "INVITE_EVENT",
    "BLOCKED_USERS", "BLOCKED_USER_EVENT", "COMMERCE", "COMMERCE_EVENT",
    "CONTENT", "DOWNLOAD_EVENT", "FRIENDS", "FRIENDS_EVENT", "IGO",
    "IGO_EVENT", "LOGIN_EVENT", "ONLINE_STATUS_EVENT", "PERMISSION",
    "PRESENCE", "PRESENCE_EVENT", "PROFILE_EVENT", "PROGRESSIVE_INSTALLATION",
    "PROGRESSIVE_INSTALLATION_EVENT", "PROFILE", "RESOURCES", "SDK",
    "UTILITY", "GET_USERID", "XMPP",
)


def load_probe_context(offer_id: str | None, *, answer_startup: bool, answer_session: bool):
    """Authorize an explicitly selected title; never reuse BFN's server codes for it."""
    selected = offer_id or "Origin.OFR.50.0004873"
    if answer_session and selected != "Origin.OFR.50.0004873":
        raise ValueError("session/auth-code replies are implemented for BFN only")
    snapshot = None
    content_id = "194814"
    if offer_id is not None or answer_startup:
        loaded = load_snapshot_dpapi(Path("private/ea_library.dpapi"))
        content_id = owned_content_id(loaded, selected)
        if answer_startup:
            snapshot = loaded
    return content_id, frozenset({selected, content_id}), snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=30, help="observation duration; 0 runs until stopped")
    parser.add_argument("--exclusive", action="store_true", help="reserve LSX ports exclusively for a managed session")
    parser.add_argument("--offer-id", help="explicit active owned title for diagnostic identity/startup replies (default: BFN)")
    parser.add_argument("--trace", action="store_true", help="print redacted decoded LSX and launcher HTTP exchanges")
    parser.add_argument("--send-challenge", action="store_true", help="send a fresh diagnostic LSX challenge on port 3216")
    parser.add_argument("--ack-challenge", action="store_true", help="acknowledge the diagnostic challenge response")
    parser.add_argument("--answer-config", action="store_true", help="answer GetConfig after the authenticated LSX handshake")
    parser.add_argument("--answer-startup", action="store_true", help="answer account-backed BFN SDK startup requests")
    parser.add_argument("--disable-overlay", action="store_true", help="diagnostic: report IGO enabled/available as false")
    parser.add_argument("--answer-session", action="store_true", help="answer local presence and request fresh EA-issued BFN game auth codes")
    parser.add_argument("--answer-license", action="store_true", help="exchange an owned Unravel Two SDK ticket for an EA-issued license")
    args = parser.parse_args()
    if args.seconds < 0:
        parser.error("--seconds must be nonnegative")
    if args.disable_overlay and not args.answer_startup:
        parser.error("--disable-overlay requires --answer-startup")
    if args.answer_session and not args.answer_startup:
        parser.error("--answer-session requires --answer-startup")
    if args.answer_license and (not args.answer_startup or args.offer_id != "Origin.OFR.50.0002520"):
        parser.error("--answer-license requires --answer-startup and the explicit Unravel Two offer")
    tracer = ConsoleTrace(args.trace, stream=sys.stdout)
    content_id, content_ids, snapshot = load_probe_context(
        args.offer_id, answer_startup=args.answer_startup, answer_session=args.answer_session
    )
    license_session = OwnedLicenseSession(snapshot, args.offer_id, Path(__file__).resolve().parents[1]) if args.answer_license else None
    game_session = None
    if args.answer_session:
        tokens = refresh_saved_tokens(Path("private/ea_bootstrap.dpapi"), Path("private/ea_tokens.dpapi"), trace=tracer)
        game_session = BfnLsxSession(snapshot, lambda: fetch_bfn_auth_code(tokens.access_token, trace=tracer))
    selector = selectors.DefaultSelector()
    listeners = []
    buffers: dict[socket.socket, bytes] = {}
    acknowledged: set[socket.socket] = set()
    challenges: dict[socket.socket, str] = {}
    client_keys: dict[socket.socket, str] = {}
    codec_keys: dict[socket.socket, bytes] = {}
    started = time.monotonic()
    for port in (3216, 3217):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        option = socket.SO_EXCLUSIVEADDRUSE if args.exclusive else socket.SO_REUSEADDR
        listener.setsockopt(socket.SOL_SOCKET, option, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen()
        listener.setblocking(False)
        selector.register(listener, selectors.EVENT_READ, ("listener", port))
        listeners.append(listener)
    print("LSX probe listening on loopback ports 3216 and 3217", flush=True)
    deadline = time.monotonic() + args.seconds if args.seconds else None
    try:
        while deadline is None or time.monotonic() < deadline:
            for key, _ in selector.select(timeout=0.5):
                kind, port = key.data
                if kind == "listener":
                    peer, _ = key.fileobj.accept()
                    if port == 3216 and args.send_challenge:
                        challenge = secrets.token_hex(16)
                        packet = (
                            '<LSX><Event sender="EALS"><Challenge '
                            f'key="{challenge}" version="13,809,0,6322" '
                            'build="release"/></Event></LSX>\0'
                        ).encode("ascii")
                        peer.sendall(packet)
                        tracer.lsx("S->G", packet)
                        challenges[peer] = challenge
                        print(f"{time.monotonic()-started:.3f}s sent diagnostic LSX challenge", flush=True)
                    peer.setblocking(False)
                    selector.register(peer, selectors.EVENT_READ, ("peer", port))
                    buffers[peer] = b""
                    print(f"{time.monotonic()-started:.3f}s accepted LSX connection on {port}", flush=True)
                    continue
                try:
                    data = key.fileobj.recv(65536)
                except (ConnectionResetError, OSError):
                    data = b""
                if not data:
                    selector.unregister(key.fileobj)
                    buffers.pop(key.fileobj, None)
                    acknowledged.discard(key.fileobj)
                    challenges.pop(key.fileobj, None)
                    client_keys.pop(key.fileobj, None)
                    codec_keys.pop(key.fileobj, None)
                    key.fileobj.close()
                    print(f"{time.monotonic()-started:.3f}s LSX connection on {port} closed", flush=True)
                    continue
                # Parse complete NUL-framed packets; never print credential values.
                buffers[key.fileobj] += data
                while b"\0" in buffers[key.fileobj]:
                    packet, buffers[key.fileobj] = buffers[key.fileobj].split(b"\0", 1)
                    tags = re.findall(rb"<([A-Za-z][A-Za-z0-9]*)\b", packet)
                    names = [tag.decode("ascii") for tag in tags[:8]]
                    if names:
                        tracer.lsx("G->S", packet)
                    print(f"{time.monotonic()-started:.3f}s received {len(packet)+1} bytes on {port}; tags={names}", flush=True)
                    if not names and packet:
                        looks_hex = re.fullmatch(rb"[0-9A-Fa-f]+", packet) is not None
                        print(f"{time.monotonic()-started:.3f}s opaque packet: ascii_hex={looks_hex}, length={len(packet)}", flush=True)
                        decoded = None
                        if looks_hex and key.fileobj in codec_keys:
                            decoded = _decrypt_packet(packet, codec_keys[key.fileobj])
                        if decoded is not None:
                            tracer.lsx("G->S", decoded)
                            decoded_tags = re.findall(rb"<([A-Za-z][A-Za-z0-9]*)\b", decoded)
                            print(f"{time.monotonic()-started:.3f}s decoded LSX tags={[x.decode('ascii') for x in decoded_tags[:8]]}", flush=True)
                            if args.answer_config or args.answer_startup:
                                try:
                                    decoded_root = ET.fromstring(decoded)
                                    decoded_request = decoded_root[0]
                                    request_id = decoded_request.attrib.get("id", "")
                                    recipient = decoded_request.attrib.get("recipient", "")
                                    is_config = decoded_request.tag == "Request" and decoded_request[0].tag == "GetConfig"
                                except (ET.ParseError, IndexError):
                                    decoded_request = None
                                    is_config = False
                                if snapshot is not None and decoded_request is not None:
                                    if decoded_request[0].tag in ("GetSetting", "GetGameInfo"):
                                        discriminator = decoded_request[0].attrib.get(
                                            "SettingId" if decoded_request[0].tag == "GetSetting" else "GameInfoId", ""
                                        )
                                        if re.fullmatch(r"[A-Z_]{1,40}", discriminator):
                                            print(f"{time.monotonic()-started:.3f}s requested {decoded_request[0].tag} {discriminator}", flush=True)
                                    response = diagnostic_startup_reply(
                                        decoded_request, snapshot, disable_overlay=args.disable_overlay,
                                        content_id=content_id,
                                    )
                                    if response is None and license_session is not None:
                                        response = license_session.reply(decoded_request)
                                        if decoded_request[0].tag == "RequestLicense":
                                            print(f"{time.monotonic()-started:.3f}s license requests={license_session.requests}, issued={license_session.successes}, shape={license_session.request_shape}, error={license_session.last_error}", flush=True)
                                    if response is None and game_session is not None:
                                        response = game_session.reply(decoded_request)
                                        if decoded_request[0].tag == "GetAuthCode":
                                            print(f"{time.monotonic()-started:.3f}s game auth requests={game_session.auth_code_requests}, issued={game_session.auth_code_successes}, error={game_session.last_auth_error}", flush=True)
                                    if response is not None:
                                        key.fileobj.sendall(_encrypt_packet(response, codec_keys[key.fileobj]))
                                        tracer.lsx("S->G", response)
                                        print(f"{time.monotonic()-started:.3f}s sent encrypted {decoded_request[0].tag} response", flush=True)
                                elif is_config and recipient == "EbisuSDK" and re.fullmatch(r"[0-9]+", request_id):
                                    services = "".join(
                                        f'<Service Name="EbisuSDK" Facility="{name}"/>'
                                        for name in _CONFIG_FACILITIES
                                    )
                                    response = (
                                        f'<LSX><Response id="{request_id}" sender="EbisuSDK">'
                                        f'<GetConfigResponse>{services}</GetConfigResponse>'
                                        '</Response></LSX>'
                                    ).encode("ascii")
                                    key.fileobj.sendall(_encrypt_packet(response, codec_keys[key.fileobj]))
                                    tracer.lsx("S->G", response)
                                    print(f"{time.monotonic()-started:.3f}s sent encrypted GetConfigResponse", flush=True)
                        if looks_hex and len(packet) % 32 == 0:
                            ciphertext = bytes.fromhex(packet.decode("ascii"))
                            candidates = [("static", _LSX_TEST_KEY)]
                            if key.fileobj in challenges:
                                candidates.append(("server_challenge", bytes.fromhex(challenges[key.fileobj])))
                            if key.fileobj in client_keys:
                                candidates.append(("client_challenge", bytes.fromhex(client_keys[key.fileobj])))
                            if key.fileobj in codec_keys:
                                candidates.append(("version3_codec", codec_keys[key.fileobj]))
                            for label, candidate_key in candidates:
                                for mode_name, mode in (("ECB", modes.ECB()), ("CBC_zero", modes.CBC(bytes(16)))):
                                    decryptor = Cipher(algorithms.AES(candidate_key), mode).decryptor()
                                    plain = decryptor.update(ciphertext) + decryptor.finalize()
                                    marker = plain.find(b"<LSX>")
                                    if marker >= 0:
                                        decoded_tags = re.findall(rb"<([A-Za-z][A-Za-z0-9]*)\b", plain)
                                        print(f"{time.monotonic()-started:.3f}s decoded {label}/{mode_name}; tags={[x.decode('ascii') for x in decoded_tags[:8]]}", flush=True)
                    if args.ack_challenge and key.fileobj not in acknowledged:
                        try:
                            root = ET.fromstring(packet)
                            request = root[0]
                            is_challenge = request.tag == "Request" and request[0].tag == "ChallengeResponse"
                            request_id = request.attrib.get("id", "")
                        except (ET.ParseError, IndexError):
                            continue
                        if is_challenge and re.fullmatch(r"[0-9]+", request_id):
                            client_key = request[0].attrib.get("key", "")
                            checks = challenge_checks(
                                request[0], challenges.get(key.fileobj), content_ids=content_ids
                            )
                            valid = all(checks.values())
                            print(f"{time.monotonic()-started:.3f}s challenge proof valid={valid}; checks={checks}", flush=True)
                            if not valid:
                                continue
                            encrypted_key = _encrypt_challenge_value(client_key)
                            client_keys[key.fileobj] = client_key
                            codec_keys[key.fileobj] = _codec_key(encrypted_key)
                            response = (
                                '<LSX><Response sender="EALS" '
                                f'id="{request_id}"><ChallengeAccepted '
                                f'response="{encrypted_key}"/></Response></LSX>\0'
                            ).encode("ascii")
                            key.fileobj.sendall(response)
                            tracer.lsx("S->G", response)
                            acknowledged.add(key.fileobj)
                            print(f"{time.monotonic()-started:.3f}s sent ChallengeAccepted", flush=True)
    finally:
        for key in list(selector.get_map().values()):
            selector.unregister(key.fileobj)
            key.fileobj.close()
        selector.close()


if __name__ == "__main__":
    main()
