"""Proves password reset and email verification end-to-end through the
real API: request-reset never reveals whether an email is registered,
reset actually changes the password (old rejected, new works), a reset
token is single-use, and registration's verify token flips
UserAccount.email_verified.
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


def _login(client: TestClient, email: str, password: str = "correct horse battery") -> dict:
    response = client.post("/auth/token", json={"client_id": email, "client_secret": password})
    assert response.status_code == 200
    return response.json()


def _protected_request(client: TestClient, access_token: str):
    return client.get("/graph/statutes", headers={"Authorization": f"Bearer {access_token}"})


class TestPasswordReset:
    def test_request_reset_for_a_registered_email_returns_a_token(self, client):
        _register(client, "alice@example.com")

        response = client.post("/auth/request-password-reset", json={"email": "alice@example.com"})
        assert response.status_code == 200
        assert response.json()["reset_token"] is not None

    def test_request_reset_for_an_unregistered_email_still_returns_200_with_no_token(self, client):
        """Anti-enumeration: the response must not reveal whether the
        email exists."""
        response = client.post("/auth/request-password-reset", json={"email": "nobody@example.com"})
        assert response.status_code == 200
        assert response.json()["reset_token"] is None

    def test_reset_actually_changes_the_password(self, client):
        _register(client, "bob@example.com")
        reset_token = client.post(
            "/auth/request-password-reset", json={"email": "bob@example.com"}
        ).json()["reset_token"]

        reset_resp = client.post(
            "/auth/reset-password", json={"reset_token": reset_token, "new_password": "new password here"}
        )
        assert reset_resp.status_code == 200
        assert reset_resp.json()["reset"] is True

        old_login = client.post(
            "/auth/token", json={"client_id": "bob@example.com", "client_secret": "correct horse battery"}
        )
        assert old_login.status_code == 401

        new_login = client.post(
            "/auth/token", json={"client_id": "bob@example.com", "client_secret": "new password here"}
        )
        assert new_login.status_code == 200

    def test_reset_token_is_single_use(self, client):
        _register(client, "carol@example.com")
        reset_token = client.post(
            "/auth/request-password-reset", json={"email": "carol@example.com"}
        ).json()["reset_token"]

        first = client.post(
            "/auth/reset-password", json={"reset_token": reset_token, "new_password": "first new password"}
        )
        assert first.status_code == 200

        second = client.post(
            "/auth/reset-password", json={"reset_token": reset_token, "new_password": "second new password"}
        )
        assert second.status_code == 401

    def test_an_access_token_cannot_be_used_to_reset_a_password(self, client):
        tokens = _register(client, "dave@example.com")
        response = client.post(
            "/auth/reset-password",
            json={"reset_token": tokens["access_token"], "new_password": "new password here"},
        )
        assert response.status_code == 401

    def test_reset_revokes_every_other_active_session_not_just_the_reset_token(self, client):
        """The actual point of TokenLedger.revoke_all_sessions_for_subject:
        a password reset is exactly the "assume this account may be
        compromised" moment a session-wide invalidation exists for."""
        registration_session = _register(client, "ivy@example.com")
        second_session = _login(client, "ivy@example.com")
        assert _protected_request(client, registration_session["access_token"]).status_code == 200
        assert _protected_request(client, second_session["access_token"]).status_code == 200

        reset_token = client.post(
            "/auth/request-password-reset", json={"email": "ivy@example.com"}
        ).json()["reset_token"]
        client.post(
            "/auth/reset-password", json={"reset_token": reset_token, "new_password": "new password here"}
        )

        assert _protected_request(client, registration_session["access_token"]).status_code == 401
        assert _protected_request(client, second_session["access_token"]).status_code == 401

    def test_reset_does_not_affect_a_different_users_session(self, client):
        _register(client, "jack@example.com")
        other_tokens = _register(client, "kelly@example.com")

        reset_token = client.post(
            "/auth/request-password-reset", json={"email": "jack@example.com"}
        ).json()["reset_token"]
        client.post(
            "/auth/reset-password", json={"reset_token": reset_token, "new_password": "new password here"}
        )

        assert _protected_request(client, other_tokens["access_token"]).status_code == 200


class TestEmailVerification:
    def test_register_issues_a_verify_token(self, client):
        tokens = _register(client, "erin@example.com")
        assert tokens["verify_token"]

    def test_verify_email_succeeds_with_the_registration_token(self, client):
        tokens = _register(client, "frank@example.com")
        response = client.post("/auth/verify-email", json={"verify_token": tokens["verify_token"]})
        assert response.status_code == 200
        assert response.json()["verified"] is True

    def test_verifying_twice_is_a_harmless_no_op(self, client):
        tokens = _register(client, "grace@example.com")
        first = client.post("/auth/verify-email", json={"verify_token": tokens["verify_token"]})
        second = client.post("/auth/verify-email", json={"verify_token": tokens["verify_token"]})
        assert first.status_code == 200
        assert second.status_code == 200

    def test_a_refresh_token_cannot_be_used_to_verify_email(self, client):
        tokens = _register(client, "henry@example.com")
        response = client.post("/auth/verify-email", json={"verify_token": tokens["refresh_token"]})
        assert response.status_code == 401
