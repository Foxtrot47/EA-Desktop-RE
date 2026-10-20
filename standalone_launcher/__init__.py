"""Protocol primitives for an EA Desktop independent launcher."""

from .auth import (
    DEFAULT_AUTH_BASE,
    DEFAULT_CLIENT_ID,
    DEFAULT_REDIRECT_URI,
    AuthRedirect,
    MissingPcSignError,
    PkcePair,
    build_authorization_url,
    build_code_token_form,
    build_refresh_token_form,
    generate_nonce,
    generate_pkce,
    parse_authorization_redirect,
    redact_auth_mapping,
)
from .pcsign import PcSignPayload, build_pc_sign, derive_mid, fnv1a_64, normalize_pc_sign_mac

__all__ = [
    "DEFAULT_AUTH_BASE",
    "DEFAULT_CLIENT_ID",
    "DEFAULT_REDIRECT_URI",
    "AuthRedirect",
    "MissingPcSignError",
    "PkcePair",
    "build_authorization_url",
    "build_code_token_form",
    "build_refresh_token_form",
    "generate_nonce",
    "generate_pkce",
    "parse_authorization_redirect",
    "redact_auth_mapping",
    "PcSignPayload",
    "build_pc_sign",
    "derive_mid",
    "fnv1a_64",
    "normalize_pc_sign_mac",
]
