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
