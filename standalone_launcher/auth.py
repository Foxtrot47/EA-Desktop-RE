"""Pure protocol helpers for EA's desktop OAuth flow.

This module deliberately performs no HTTP and never reads EA Desktop state.
The caller supplies the build-specific ``pc_sign`` value and OAuth client
secret. Keeping those inputs explicit makes request construction testable and
prevents either value from being written to logs by this layer.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import string
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import parse_qs, urlencode, urlparse

DEFAULT_AUTH_BASE = "https://accounts.ea.com"
DEFAULT_CLIENT_ID = "JUNO_PC_CLIENT"
DEFAULT_REDIRECT_URI = "qrc:///html/login_successful.html"
DEFAULT_DISPLAY = "junoClient/login"

_PKCE_ALPHABET = string.ascii_letters + string.digits + "-._~"
_SECRET_FIELDS = frozenset(
    {
        "access_token",
        "authorization",
        "client_secret",
        "code",
        "code_verifier",
        "id_token",
        "pc_sign",
        "refresh_token",
        "remid",
        "sid",
    }
)


class AuthProtocolError(ValueError):
    """Raised when an OAuth request or redirect violates the recovered flow."""


class MissingPcSignError(AuthProtocolError):
    """Raised when the mandatory EA request signature was not supplied."""


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str


@dataclass(frozen=True)
class AuthRedirect:
    code: str | None
    error: str | None
    error_code: str | None
    error_number: str | None
    state: str | None

    @property
    def succeeded(self) -> bool:
        return self.code is not None and self.error is None


def _base64url_no_padding(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def generate_pkce(*, verifier: str | None = None) -> PkcePair:
    """Return an RFC 7636 S256 verifier/challenge pair."""
    if verifier is None:
        verifier = "".join(secrets.choice(_PKCE_ALPHABET) for _ in range(64))
    if not 43 <= len(verifier) <= 128:
        raise AuthProtocolError("PKCE verifier must be 43 through 128 characters")
    if any(character not in _PKCE_ALPHABET for character in verifier):
        raise AuthProtocolError("PKCE verifier contains a character outside RFC 7636")
    challenge = _base64url_no_padding(hashlib.sha256(verifier.encode("ascii")).digest())
    return PkcePair(verifier=verifier, challenge=challenge)


def generate_nonce() -> str:
    """Return the decimal nonce shape emitted by the desktop client."""
    return str(secrets.randbits(31))


def build_authorization_url(
    *,
    pc_sign: str,
    code_challenge: str,
    nonce: str | None = None,
    locale: str = "en_US",
    client_id: str = DEFAULT_CLIENT_ID,
    auth_base: str = DEFAULT_AUTH_BASE,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    sbiod_enabled: bool = True,
    scope: str | None = None,
    state: str | None = None,
    is_steam_deck: bool = False,
) -> str:
    """Construct the recovered ``/connect/auth`` interactive-login URL."""
    if not pc_sign or "." not in pc_sign:
        raise MissingPcSignError("EA /connect/auth requires a payload.signature pc_sign")
    if not code_challenge:
        raise AuthProtocolError("code_challenge is required")

    parameters: list[tuple[str, str]] = [
        ("client_id", client_id),
        ("sbiod_enabled", str(sbiod_enabled).lower()),
        ("code_challenge", code_challenge),
        ("code_challenge_method", "S256"),
        ("redirect_uri", redirect_uri),
        ("display", DEFAULT_DISPLAY),
        ("locale", locale),
        ("pc_sign", pc_sign),
        ("nonce", nonce or generate_nonce()),
        ("response_type", "code"),
    ]
    if scope:
        parameters.append(("scope", scope))
    if state:
        parameters.append(("state", state))
    if is_steam_deck:
        parameters.append(("is_sd", "true"))
    return f"{auth_base.rstrip('/')}/connect/auth?{urlencode(parameters)}"


def parse_authorization_redirect(
    url: str,
    *,
    expected_redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> AuthRedirect:
    """Validate the intercepted QRC redirect and extract its result fields."""
    actual = urlparse(url)
    expected = urlparse(expected_redirect_uri)
    if (actual.scheme, actual.netloc, actual.path) != (
        expected.scheme,
        expected.netloc,
        expected.path,
    ):
        raise AuthProtocolError("authorization redirect URI does not match the registered URI")

    # AuthCodeRequestor also accepts providers that return the result fragment.
    query = actual.query or actual.fragment
    values = parse_qs(query, keep_blank_values=True)

    def one(name: str) -> str | None:
        found = values.get(name)
        return found[0] if found else None

    result = AuthRedirect(
        code=one("code"),
        error=one("error"),
        error_code=one("error_code"),
        error_number=one("error_number"),
        state=one("state"),
    )
    if result.code is None and result.error is None:
        raise AuthProtocolError("authorization redirect contains neither code nor error")
    return result


def build_code_token_form(
    *,
    code: str,
    code_verifier: str,
    client_secret: str,
    client_id: str = DEFAULT_CLIENT_ID,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> dict[str, str]:
    """Build the form body for the recovered authorization-code exchange."""
    if not all((code, code_verifier, client_secret)):
        raise AuthProtocolError("code, code_verifier, and client_secret are required")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
    }


def build_refresh_token_form(
    *,
    refresh_token: str,
    client_secret: str,
    client_id: str = DEFAULT_CLIENT_ID,
    refresh_tos: bool = False,
) -> dict[str, str]:
    """Build the form body for EA's refresh-token branch."""
    if not refresh_token or not client_secret:
        raise AuthProtocolError("refresh_token and client_secret are required")
    result = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if refresh_tos:
        result["refresh_tos"] = "true"
    return result


def redact_auth_mapping(values: Mapping[str, object]) -> dict[str, object]:
    """Copy a mapping while replacing credential-bearing values."""
    return {
        key: "<redacted>" if key.casefold() in _SECRET_FIELDS else value
        for key, value in values.items()
    }
