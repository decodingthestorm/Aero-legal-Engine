"""Minimal, dependency-free HS256 JWT create/verify.

A full JWT library (PyJWT, python-jose) would normally be the right call
for a production auth system — multiple algorithms, JWKS, refresh tokens,
and so on. This API only ever issues and checks HS256 tokens signed with a
single shared secret (settings.jwt_secret), which is simple enough to
implement correctly against RFC 7519 with just the standard library, so
that's what this does rather than adding a dependency for a few dozen
lines of base64/HMAC.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time

from legal_engine.core.config import settings


class InvalidTokenError(Exception):
    """Raised when a JWT fails signature verification, is expired, or is malformed."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(subject: str, tenant_id: str, expires_minutes: int | None = None) -> str:
    expires_minutes = expires_minutes if expires_minutes is not None else settings.jwt_expires_minutes
    header = {"alg": settings.jwt_algorithm, "typ": "JWT"}
    now = int(time.time())
    payload = {"sub": subject, "tenant_id": tenant_id, "iat": now, "exp": now + expires_minutes * 60}

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

    signature = hmac.new(settings.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"


def decode_token(token: str) -> dict:
    """Returns the token's full validated payload (including any custom
    claims like ``tenant_id``) if the signature verifies and it hasn't
    expired. Raises InvalidTokenError otherwise."""
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidTokenError("Token is not a three-part JWT")
    header_b64, payload_b64, signature_b64 = parts

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_signature = hmac.new(
        settings.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    try:
        actual_signature = _b64url_decode(signature_b64)
    except (ValueError, binascii.Error) as exc:
        raise InvalidTokenError("Token signature is not valid base64url") from exc

    if not hmac.compare_digest(expected_signature, actual_signature):
        raise InvalidTokenError("Token signature does not verify")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidTokenError("Token payload is not valid JSON") from exc

    if payload.get("exp", 0) < time.time():
        raise InvalidTokenError("Token has expired")

    return payload


def verify_token(token: str) -> str:
    """Returns the token's subject if valid. Raises InvalidTokenError otherwise."""
    payload = decode_token(token)
    subject = payload.get("sub")
    if not subject:
        raise InvalidTokenError("Token is missing a subject")
    return str(subject)


def get_token_tenant(token: str) -> str:
    """Returns the token's tenant_id claim if valid. Raises
    InvalidTokenError if the token itself is invalid, or if it's valid but
    has no tenant_id claim (e.g. a token issued before multi-tenancy)."""
    payload = decode_token(token)
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise InvalidTokenError("Token is missing a tenant_id claim")
    return str(tenant_id)
