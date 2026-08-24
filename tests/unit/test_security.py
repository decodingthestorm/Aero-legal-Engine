import time

import pytest

from legal_engine.api.security import InvalidTokenError, create_token, verify_token


class TestJWT:
    def test_create_and_verify_roundtrip(self):
        token = create_token(subject="demo")
        assert verify_token(token) == "demo"

    def test_malformed_token_raises(self):
        with pytest.raises(InvalidTokenError, match="three-part"):
            verify_token("not-a-jwt")

    def test_tampered_payload_is_rejected(self):
        token = create_token(subject="demo")
        header_b64, payload_b64, signature_b64 = token.split(".")
        tampered = f"{header_b64}.{payload_b64}extra.{signature_b64}"
        with pytest.raises(InvalidTokenError, match="signature"):
            verify_token(tampered)

    def test_forged_signature_is_rejected(self):
        token = create_token(subject="demo")
        header_b64, payload_b64, _ = token.split(".")
        with pytest.raises(InvalidTokenError, match="signature"):
            verify_token(f"{header_b64}.{payload_b64}.AAAAAAAAAAAAAAAAAAAAAAAAAAAA")

    def test_expired_token_is_rejected(self):
        token = create_token(subject="demo", expires_minutes=0)
        time.sleep(1.1)
        with pytest.raises(InvalidTokenError, match="expired"):
            verify_token(token)

    def test_signed_with_different_secret_is_rejected(self, monkeypatch):
        from legal_engine.core.config import settings

        token = create_token(subject="demo")
        monkeypatch.setattr(settings, "jwt_secret", "a-completely-different-secret")
        with pytest.raises(InvalidTokenError, match="signature"):
            verify_token(token)
