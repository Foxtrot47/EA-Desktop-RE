"""Interactive standalone OAuth login using the small WebView2 auth host."""

from __future__ import annotations

import json
import os
import secrets as random_secrets
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib import error, parse, request

from .auth import (
    AuthProtocolError,
    build_authorization_url,
    build_code_token_form,
    build_refresh_token_form,
    generate_pkce,
    parse_authorization_redirect,
)
from .bootstrap import StandaloneSecrets, dpapi_protect, dpapi_unprotect, load_dpapi
from .console_trace import ConsoleTrace
from .machine import collect_local_machine_fields, make_pc_sign_payload
from .pcsign import build_pc_sign, format_pc_sign_timestamp


DEFAULT_TOKEN_URL = "https://accounts.ea.com/connect/token"


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    token_type: str
    expires_in: int
    id_token: str | None = None
    scope: str | None = None

    @classmethod
    def from_response(
        cls,
        document: dict[str, object],
        previous: "TokenSet | None" = None,
    ) -> "TokenSet":
        access_token = document.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise AuthProtocolError("token response does not contain an access token")
        return cls(
            access_token=access_token,
            refresh_token=(
                document.get("refresh_token")
                if isinstance(document.get("refresh_token"), str)
                else previous.refresh_token if previous else None
            ),
            token_type=str(document.get("token_type") or "Bearer"),
            expires_in=int(document.get("expires_in") or 0),
            id_token=(
                document.get("id_token")
                if isinstance(document.get("id_token"), str)
                else previous.id_token if previous else None
            ),
            scope=(
                document.get("scope")
                if isinstance(document.get("scope"), str)
                else previous.scope if previous else None
            ),
        )


def create_authorization_request(secrets: StandaloneSecrets) -> tuple[str, str]:
    fields = collect_local_machine_fields()
    index = random_secrets.randbelow(len(secrets.production_pc_sign_keys))
    payload = make_pc_sign_payload(
        fields,
        format_pc_sign_timestamp(datetime.now()),
        index + 1,
    )
    pc_sign = build_pc_sign(payload, secrets.production_pc_sign_keys[index])
    pkce = generate_pkce()
    return build_authorization_url(pc_sign=pc_sign, code_challenge=pkce.challenge), pkce.verifier


def run_auth_host(host_dll: Path, authorization_url: str) -> str:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        ["dotnet", str(host_dll)],
        input=authorization_url + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=creationflags,
    )
    redirect_url = completed.stdout.strip()
    if completed.returncode != 0 or not redirect_url:
        raise AuthProtocolError(f"login window closed without an authorization result (host exit {completed.returncode})")
    return redirect_url


def exchange_authorization_code(
    code: str,
    verifier: str,
    client_secret: str,
    token_url: str = DEFAULT_TOKEN_URL,
) -> TokenSet:
    form = build_code_token_form(code=code, code_verifier=verifier, client_secret=client_secret)
    body = parse.urlencode(form).encode("ascii")
    token_request = request.Request(
        token_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(token_request, timeout=30) as response:
            document = json.load(response)
    except error.HTTPError as exc:
        # The response body may contain protocol details, but can also echo
        # credential-bearing material. Keep it out of exception/log strings.
        raise AuthProtocolError(f"token exchange failed with HTTP {exc.code}") from None
    return TokenSet.from_response(document)


def exchange_refresh_token(
    previous: TokenSet,
    client_secret: str,
    token_url: str = DEFAULT_TOKEN_URL,
    *,
    trace: ConsoleTrace | None = None,
) -> TokenSet:
    if not previous.refresh_token:
        raise AuthProtocolError("saved token set has no refresh token")
    form = build_refresh_token_form(
        refresh_token=previous.refresh_token,
        client_secret=client_secret,
    )
    body = parse.urlencode(form).encode("ascii")
    token_request = request.Request(
        token_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    tracer = trace or ConsoleTrace()
    tracer.http_request("POST", token_url, fields=form)
    try:
        with request.urlopen(token_request, timeout=30) as response:
            document = json.load(response)
            tracer.http_response("POST", token_url, getattr(response, "status", None), fields=document)
    except error.HTTPError as exc:
        tracer.http_response("POST", token_url, exc.code)
        raise AuthProtocolError(f"token refresh failed with HTTP {exc.code}") from None
    except (error.URLError, OSError, ValueError):
        tracer.http_failure("POST", token_url)
        raise
    return TokenSet.from_response(document, previous)


def save_tokens_dpapi(path: Path, tokens: TokenSet) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    value = json.dumps(asdict(tokens), sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(dpapi_protect(value, "EA standalone launcher OAuth tokens"))


def load_tokens_dpapi(path: Path) -> TokenSet:
    return TokenSet(**json.loads(dpapi_unprotect(path.read_bytes())))


def interactive_login(secret_store: Path, host_dll: Path, token_store: Path) -> TokenSet:
    secrets = load_dpapi(secret_store)
    authorization_url, verifier = create_authorization_request(secrets)
    redirect = parse_authorization_redirect(run_auth_host(host_dll, authorization_url))
    if not redirect.succeeded or not redirect.code:
        raise AuthProtocolError(f"EA authorization failed: {redirect.error or 'unknown error'}")
    client_secret = secrets.client_secret_by_environment[0]
    tokens = exchange_authorization_code(redirect.code, verifier, client_secret)
    save_tokens_dpapi(token_store, tokens)
    return tokens


def refresh_saved_tokens(secret_store: Path, token_store: Path, *, trace: ConsoleTrace | None = None) -> TokenSet:
    secrets = load_dpapi(secret_store)
    previous = load_tokens_dpapi(token_store)
    refreshed = exchange_refresh_token(previous, secrets.client_secret_by_environment[0], trace=trace)
    save_tokens_dpapi(token_store, refreshed)
    return refreshed
