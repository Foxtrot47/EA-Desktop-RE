"""Obtain BFN's online game authorization code using the signed-in EA account.

Observed request: /connect/auth with client_id, release_type, response_type,
and access_token. Unlike desktop interactive login, this uses neither PKCE nor
pc_sign. Credentials and the returned one-time code must remain in memory.
"""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .console_trace import ConsoleTrace


BFN_CLIENT_ID = "PVZGW3-PC-SERVER-BLAZE"
AUTH_ENDPOINT = "https://accounts.ea.com/connect/auth"


class GameAuthError(RuntimeError):
    """Credential-free diagnostic for a failed authorized game-code request."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_game_code_redirect(location: str) -> str:
    parsed = urlparse(location)
    values = parse_qs(parsed.query or parsed.fragment, keep_blank_values=True)
    codes = values.get("code", [])
    if "error" in values or len(codes) != 1 or not codes[0]:
        raise GameAuthError("EA game authorization redirect did not contain one valid code")
    return codes[0]


def fetch_bfn_auth_code(access_token: str, *, trace: ConsoleTrace | None = None) -> str:
    """Request a fresh EA-issued code; never follow its redirect or log its URL."""
    if not access_token:
        raise GameAuthError("A signed-in standalone account is required")
    fields = {
        "client_id": BFN_CLIENT_ID, "release_type": "prod",
        "response_type": "code", "access_token": access_token,
    }
    query = urlencode(fields)
    tracer = trace or ConsoleTrace()
    tracer.http_request("GET", AUTH_ENDPOINT, fields=fields)
    opener = build_opener(_NoRedirect())
    request = Request(f"{AUTH_ENDPOINT}?{query}", headers={"Accept": "*/*"})
    try:
        with opener.open(request, timeout=10) as response:
            # AuthCodeRequestor accepts the original 302, not a final login page.
            status = response.status
            location = response.headers.get("Location", "")
    except HTTPError as exc:
        status = exc.code
        location = exc.headers.get("Location", "")
        exc.close()
        if status != 302:
            tracer.http_response("GET", AUTH_ENDPOINT, status)
            raise GameAuthError(f"EA game authorization returned HTTP {status}") from None
    except (URLError, OSError, ValueError):
        tracer.http_failure("GET", AUTH_ENDPOINT)
        raise GameAuthError("EA game authorization transport failed") from None
    tracer.http_response("GET", AUTH_ENDPOINT, status, headers={"Location": location} if location else None)
    if status == 302:
        return parse_game_code_redirect(location)
    raise GameAuthError(f"EA game authorization expected HTTP 302, received {status}")
