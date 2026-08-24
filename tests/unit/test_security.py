import time

import pytest

from legal_engine.api.security import (
    InvalidTokenError,
    create_token,
    get_token_tenant,
    verify_token,
)

TENANT = "demo-tenant"


class TestJWT:
    def test_create_and_verify_roundtrip(self):
        token = create_token(subject="demo", tenant_id=TENANT)
        assert verify_token(token) == "demo"

    def test_malformed_token_raises(self):
        with pytest.raises(InvalidTokenError, match="three-part"):
            verify_token("not-a-jwt")

    def test_tampered_payload_is_rejected(self):
        token = create_token(subject="demo", tenant_id=TENANT)
        header_b64, payload_b64, signature_b64 = token.split(".")
        tampered = f"{header_b64}.{payload_b64}extra.{signature_b64}"
        with pytest.raises(InvalidTokenError, match="signature"):
            verify_token(tampered)

    def test_forged_signature_is_rejected(self):
        token = create_token(subject="demo", tenant_id=TENANT)
        header_b64, payload_b64, _ = token.split(".")
        with pytest.raises(InvalidTokenError, match="signature"):
            verify_token(f"{header_b64}.{payload_b64}.AAAAAAAAAAAAAAAAAAAAAAAAAAAA")

    def test_expired_token_is_rejected(self):
        token = create_token(subject="demo", tenant_id=TENANT, expires_minutes=0)
        time.sleep(1.1)
        with pytest.raises(InvalidTokenError, match="expired"):
            verify_token(token)

    def test_signed_with_different_secret_is_rejected(self, monkeypatch):
        from legal_engine.core.config import settings

        token = create_token(subject="demo", tenant_id=TENANT)
        monkeypatch.setattr(settings, "jwt_secret", "a-completely-different-secret")
        with pytest.raises(InvalidTokenError, match="signature"):
            verify_token(token)


class TestTenantClaim:
    def test_get_token_tenant_roundtrip(self):
        token = create_token(subject="demo", tenant_id=TENANT)
        assert get_token_tenant(token) == TENANT

    def test_get_token_tenant_rejects_token_without_tenant_claim(self):
        import base64
        import hashlib
        import hmac
        import json

        from legal_engine.core.config import settings

        def _b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header_b64 = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload_b64 = _b64url(json.dumps({"sub": "demo", "exp": time.time() + 60}).encode())
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        signature = hmac.new(settings.jwt_secret.encode(), signing_input, hashlib.sha256).digest()
        token_without_tenant = f"{header_b64}.{payload_b64}.{_b64url(signature)}"

        with pytest.raises(InvalidTokenError, match="tenant_id"):
            get_token_tenant(token_without_tenant)
