"""Proves token revocation and refresh-token rotation end-to-end through
the real API: register -> access token works -> refresh rotates it ->
the spent refresh token is rejected on reuse -> the new access token
still works -> revoking it makes it stop working immediately (not just
once it naturally expires).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from legal_engine.api.main import app
from legal_engine.core.config import settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    with TestClient(app) as c:
        yield c


def _register(client: TestClient, email: str) -> dict:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery"})
    assert response.status_code == 200
    return response.json()


def _protected_request(client: TestClient, access_token: str):
    return client.get("/graph/statutes", headers={"Authorization": f"Bearer {access_token}"})


class TestRefreshRotation:
    def test_refresh_issues_a_new_working_access_token(self, client):
        tokens = _register(client, "alice@example.com")

        refresh_resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert refresh_resp.status_code == 200
        new_tokens = refresh_resp.json()

        assert _protected_request(client, new_tokens["access_token"]).status_code == 200

    def test_the_new_refresh_token_differs_from_the_old_one(self, client):
        tokens = _register(client, "bob@example.com")
        new_tokens = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).json()
        assert new_tokens["refresh_token"] != tokens["refresh_token"]

    def test_reusing_a_spent_refresh_token_is_rejected(self, client):
        tokens = _register(client, "carol@example.com")
        first = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert first.status_code == 200

        second = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert second.status_code == 401

    def test_an_access_token_cannot_be_used_at_refresh(self, client):
        tokens = _register(client, "dave@example.com")
        response = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
        assert response.status_code == 401

    def test_a_refresh_token_cannot_be_used_as_a_bearer_token(self, client):
        tokens = _register(client, "erin@example.com")
        response = _protected_request(client, tokens["refresh_token"])
        assert response.status_code == 401


class TestRevocation:
    def test_revoked_access_token_is_immediately_rejected(self, client):
        tokens = _register(client, "frank@example.com")
        assert _protected_request(client, tokens["access_token"]).status_code == 200

        revoke_resp = client.post("/auth/revoke", json={"token": tokens["access_token"]})
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["revoked"] is True

        assert _protected_request(client, tokens["access_token"]).status_code == 401

    def test_revoking_a_refresh_token_prevents_it_from_being_redeemed(self, client):
        tokens = _register(client, "grace@example.com")
        client.post("/auth/revoke", json={"token": tokens["refresh_token"]})

        response = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert response.status_code == 401

    def test_revocation_does_not_affect_a_different_users_token(self, client):
        alice_tokens = _register(client, "henry@example.com")
        bob_tokens = _register(client, "iris@example.com")

        client.post("/auth/revoke", json={"token": alice_tokens["access_token"]})

        assert _protected_request(client, bob_tokens["access_token"]).status_code == 200


class TestRefreshTokenReuseCascadesToTheWholeSession:
    """The actual property compliance/token_ledger.py's family_id exists
    for: a single jti's revocation isn't enough to kill a hijacked
    session on its own — the legitimate holder's already-rotated sibling
    access token would stay valid on jti-revocation alone. Reusing a
    spent refresh token has to cascade to the whole family."""

    def test_reuse_revokes_the_access_token_from_the_legitimate_rotation(self, client):
        original = _register(client, "julia@example.com")

        # The legitimate rotation.
        legitimate = client.post("/auth/refresh", json={"refresh_token": original["refresh_token"]}).json()
        assert _protected_request(client, legitimate["access_token"]).status_code == 200

        # An attacker (or a race) reuses the now-spent original refresh token.
        reuse_attempt = client.post("/auth/refresh", json={"refresh_token": original["refresh_token"]})
        assert reuse_attempt.status_code == 401

        # The cascade: the *legitimate* access token from the rotation above
        # — which was never itself revoked or reused — is now rejected too,
        # because it shares a family with the compromised refresh token.
        assert _protected_request(client, legitimate["access_token"]).status_code == 401

    def test_reuse_also_prevents_further_refresh_with_the_new_token(self, client):
        original = _register(client, "kevin@example.com")
        legitimate = client.post("/auth/refresh", json={"refresh_token": original["refresh_token"]}).json()

        client.post("/auth/refresh", json={"refresh_token": original["refresh_token"]})  # reuse

        blocked = client.post("/auth/refresh", json={"refresh_token": legitimate["refresh_token"]})
        assert blocked.status_code == 401

    def test_reuse_in_one_users_session_does_not_affect_another_users_session(self, client):
        laura_tokens = _register(client, "laura@example.com")
        mike_tokens = _register(client, "mike@example.com")

        client.post("/auth/refresh", json={"refresh_token": laura_tokens["refresh_token"]})
        client.post("/auth/refresh", json={"refresh_token": laura_tokens["refresh_token"]})  # reuse

        assert _protected_request(client, mike_tokens["access_token"]).status_code == 200

    def test_a_normal_multi_step_refresh_chain_never_triggers_a_false_cascade(self, client):
        """Refreshing repeatedly and only ever using the newest token
        (completely normal client behavior) must never be mistaken for
        reuse."""
        tokens = _register(client, "nina@example.com")
        for _ in range(3):
            tokens = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).json()

        assert _protected_request(client, tokens["access_token"]).status_code == 200
