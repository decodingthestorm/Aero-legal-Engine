"""Proves the email-verification gate end-to-end through the real API.

``UserAccount.email_verified`` was written by POST /auth/verify-email and
displayed by GET /auth/members from the day it was added, and gated
nothing. This covers the setting that makes it mean something, and — just
as importantly — the three cases that must keep working when it's on: the
demo credential, the /auth router, and the default-off path.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from legal_engine.api.main import app
from legal_engine.core.config import settings

_PASSWORD = "correct horse battery"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def enforcing(monkeypatch):
    monkeypatch.setattr(settings, "require_email_verification", True)


def _register(client: TestClient, email: str) -> dict:
    response = client.post("/auth/register", json={"email": email, "password": _PASSWORD})
    assert response.status_code == 200
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _protected(client: TestClient, token: str):
    return client.get("/graph/statutes", headers=_headers(token))


class TestDefaultIsOff:
    def test_an_unverified_account_is_not_blocked_by_default(self, client):
        """Turning this on retroactively locks out every account
        registered before it, so the default has to stay off."""
        account = _register(client, "default-off@example.com")
        assert _protected(client, account["access_token"]).status_code == 200


class TestEnforcementOn:
    def test_an_unverified_account_is_blocked(self, client, enforcing):
        account = _register(client, "unverified@example.com")

        response = _protected(client, account["access_token"])

        assert response.status_code == 403
        assert "not verified" in response.json()["detail"].lower()

    def test_verifying_unblocks_the_same_token(self, client, enforcing):
        """No re-login needed — the check reads the account on each
        request rather than anything baked into the token."""
        account = _register(client, "verifies@example.com")
        assert _protected(client, account["access_token"]).status_code == 403

        verify = client.post("/auth/verify-email", json={"verify_token": account["verify_token"]})
        assert verify.status_code == 200

        assert _protected(client, account["access_token"]).status_code == 200

    def test_consent_gated_routes_are_covered_too(self, client, enforcing):
        """/verification and /simulation inherit the protected
        dependencies, so the gate reaches them as well."""
        account = _register(client, "consent-gated@example.com")
        client.post("/legal/accept", headers=_headers(account["access_token"]))

        response = client.post(
            "/simulation/penalty",
            json={"benefit": 100, "cost_compliance": 10, "p_detect": 0.3},
            headers=_headers(account["access_token"]),
        )

        assert response.status_code == 403


class TestWhatMustKeepWorking:
    def test_the_demo_credential_still_works(self, client, enforcing):
        """It has no UserAccount at all — it predates registration and is
        checked directly by POST /auth/token. Requiring a verification
        flag it can never carry would break the zero-config path for no
        security gain."""
        token = client.post(
            "/auth/token",
            json={
                "client_id": settings.api_client_id,
                "client_secret": settings.api_client_secret,
            },
        ).json()["access_token"]

        assert _protected(client, token).status_code == 200

    def test_verify_email_itself_stays_reachable(self, client, enforcing):
        """The obvious deadlock: gating the route that clears the gate."""
        account = _register(client, "escape-hatch@example.com")

        response = client.post(
            "/auth/verify-email", json={"verify_token": account["verify_token"]}
        )

        assert response.status_code == 200

    def test_password_reset_stays_reachable_for_an_unverified_account(self, client, enforcing):
        """Someone who lost access before verifying would otherwise be
        stranded — they can't verify without the account and can't reset
        without verifying."""
        _register(client, "locked-out@example.com")

        response = client.post(
            "/auth/request-password-reset", json={"email": "locked-out@example.com"}
        )

        assert response.status_code == 200
        assert response.json()["reset_token"] is not None

    def test_members_listing_stays_reachable(self, client, enforcing):
        """GET /auth/members is on the /auth router, which is deliberately
        outside the gate."""
        account = _register(client, "owner-unverified@example.com")

        response = client.get("/auth/members", headers=_headers(account["access_token"]))

        assert response.status_code == 200


class TestAuthDisabled:
    def test_the_gate_no_ops_when_auth_is_off(self, monkeypatch):
        """Same contract as require_auth and require_consent: with no
        identified caller there is nothing to check."""
        monkeypatch.setattr(settings, "api_auth_enabled", False)
        monkeypatch.setattr(settings, "require_email_verification", True)

        with TestClient(app) as anonymous:
            assert anonymous.get("/graph/statutes").status_code == 200
