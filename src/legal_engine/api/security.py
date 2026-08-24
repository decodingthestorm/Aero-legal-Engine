"""Minimal, dependency-free HS256 JWT create/verify, plus password hashing.

A full JWT library (PyJWT, python-jose) would normally be the right call
for a production auth system — multiple algorithms, JWKS, refresh tokens,
and so on. This API only ever issues and checks HS256 tokens signed with a
single shared secret (settings.jwt_secret), which is simple enough to
implement correctly against RFC 7519 with just the standard library, so
that's what this does rather than adding a dependency for a few dozen
lines of base64/HMAC.

Password hashing (hash_password/verify_password) is the same philosophy
applied to a second primitive: hashlib.pbkdf2_hmac is a correct standard-
library implementation of a standard, NIST-approved algorithm — using it
correctly (a high iteration count, a random salt per password, a
constant-time comparison) isn't "rolling your own crypto" in the risky
sense, any more than the HS256 signing above is.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from uuid import uuid4

from legal_engine.core.config import settings

_PBKDF2_ITERATIONS = 600_000  # OWASP's current minimum recommendation for PBKDF2-SHA256
_PBKDF2_SALT_BYTES = 16


class InvalidTokenError(Exception):
    """Raised when a JWT fails signature verification, is expired, or is malformed."""


def hash_password(password: str) -> str:
    """Returns a self-describing hash string:
    ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``. Embedding the
    iteration count (rather than only reading it from settings at verify
    time) means a future bump to _PBKDF2_ITERATIONS doesn't invalidate —
    or silently under-verify — every password hashed under the old count;
    each hash still records exactly what it was created with."""
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Returns False (never raises) for a malformed hash string, the same
    way a wrong password just fails rather than erroring — callers
    shouldn't need to distinguish "corrupt record" from "wrong password."
    """
    try:
        algorithm, iterations_str, salt_hex, digest_hex = password_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected_digest = bytes.fromhex(digest_hex)
    except ValueError:
        return False

    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(
    subject: str,
    tenant_id: str,
    expires_minutes: int | None = None,
    token_type: str = "access",
    jti: str | None = None,
    family_id: str | None = None,
) -> str:
    """``jti`` (JWT ID) is auto-generated (uuid4) unless given explicitly —
    it's what a per-token revocation/redemption record (see
    compliance/token_ledger.py) is keyed on, since ``sub`` alone only
    identifies the *user*, not this specific token. ``token_type``
    distinguishes a normal bearer ("access") token from a refresh (or
    invite/password_reset/email_verification) token — api/dependencies.py's
    require_auth rejects anything but an "access" token presented as a
    bearer token, since every other type is meant for exactly one
    single-purpose endpoint (refresh tokens at POST /auth/refresh, etc).

    ``family_id`` is also auto-generated (uuid4) unless given explicitly —
    every access+refresh pair issued together shares one (see
    api/routes/auth.py's _issue_token_pair), carried forward unchanged
    through every POST /auth/refresh rotation. Reusing an already-redeemed
    refresh token revokes the whole family, not just that one jti — see
    compliance/token_ledger.py's revoke_family for why a single jti isn't
    enough to actually kill a hijacked session."""
    expires_minutes = expires_minutes if expires_minutes is not None else settings.jwt_expires_minutes
    header = {"alg": settings.jwt_algorithm, "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": subject,
        "tenant_id": tenant_id,
        "jti": jti if jti is not None else str(uuid4()),
        "token_type": token_type,
        "family_id": family_id if family_id is not None else str(uuid4()),
        "iat": now,
        "exp": now + expires_minutes * 60,
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

    signature = hmac.new(settings.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"


def decode_token(token: str) -> dict[str, Any]:
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
        payload: dict[str, Any] = json.loads(_b64url_decode(payload_b64))
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
