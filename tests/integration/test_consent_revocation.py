"""Proves liability-disclaimer revocation end-to-end through the real API:
an owner can withdraw a tenant's acceptance (e.g. "the person who
accepted is no longer with the organization"), which immediately blocks
/verification and /simulation again with no other action needed, and a
later re-acceptance unblocks them again.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from legal_engine.api.main import app
from legal_engine.core.config import settings

_PENALTY_BODY = {"benefit": 100, "cost_compliance": 10, "p_detect": 0.3}
_VERIFY_BODY = {
    "forall_vars": ["x"],
    "domain": ["alice"],
    "matrix": {"kind": "atom", "predicate": "Owns", "args": [{"kind": "variable", "name": "x"}]},
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    with TestClient(app) as c:
        yield c


def _register(client: TestClient, email: str) -> dict:
    response = client.post("/auth/register", json={"email": email, "password": "correct horse battery"})
    assert response.status_code == 200
    return response.json()


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _invite_and_accept(client: TestClient, owner_tokens: dict, email: str) -> dict:
    invite_token = client.post(
        "/auth/invite", json={"email": email}, headers=_auth_headers(owner_tokens["access_token"])
    ).json()["invite_token"]
    response = client.post(
        "/auth/accept-invite", json={"invite_token": invite_token, "password": "correct horse battery"}
    )
    assert response.status_code == 200
    return response.json()


class TestRevokeAcceptance:
    def test_owner_can_revoke_after_accepting(self, client):
        owner = _register(client, "owner1@example.com")
        client.post("/legal/accept", headers=_auth_headers(owner["access_token"]))

        response = client.post("/legal/revoke", json={}, headers=_auth_headers(owner["access_token"]))
        assert response.status_code == 200
        assert response.json()["revoked"] is True

    def test_verification_works_after_accepting_then_blocked_after_revoking(self, client):
        owner = _register(client, "owner2@example.com")
        headers = _auth_headers(owner["access_token"])

        client.post("/legal/accept", headers=headers)
        assert client.post("/verification/verify", json=_VERIFY_BODY, headers=headers).status_code == 200

        client.post("/legal/revoke", json={}, headers=headers)

        blocked = client.post("/verification/verify", json=_VERIFY_BODY, headers=headers)
        assert blocked.status_code == 403
        assert "disclaimer" in blocked.json()["detail"].lower()

        blocked_sim = client.post("/simulation/penalty", json=_PENALTY_BODY, headers=headers)
        assert blocked_sim.status_code == 403

    def test_no_new_token_is_needed_for_the_revocation_to_take_effect(self, client):
        """require_consent re-checks has_accepted_current_disclaimer fresh
        on every request — the *same* still-valid access token that could
        call /verification before revocation is rejected by it right
        after, with nothing about the token itself having changed."""
        owner = _register(client, "owner3@example.com")
        headers = _auth_headers(owner["access_token"])
        client.post("/legal/accept", headers=headers)

        client.post("/legal/revoke", json={}, headers=headers)

        assert client.post("/verification/verify", json=_VERIFY_BODY, headers=headers).status_code == 403

    def test_reaccepting_after_revocation_unblocks_it_again(self, client):
        owner = _register(client, "owner4@example.com")
        headers = _auth_headers(owner["access_token"])
        client.post("/legal/accept", headers=headers)
        client.post("/legal/revoke", json={}, headers=headers)

        reaccept = client.post("/legal/accept", headers=headers)
        assert reaccept.status_code == 200
        assert reaccept.json()["already_accepted"] is False

        assert client.post("/verification/verify", json=_VERIFY_BODY, headers=headers).status_code == 200

    def test_a_non_owner_cannot_revoke(self, client):
        owner = _register(client, "owner5@example.com")
        member = _invite_and_accept(client, owner, "member5@example.com")
        client.post("/legal/accept", headers=_auth_headers(owner["access_token"]))

        response = client.post(
            "/legal/revoke", json={}, headers=_auth_headers(member["access_token"])
        )
        assert response.status_code == 403

        # and the tenant's acceptance is untouched by the rejected attempt
        still_ok = client.post(
            "/verification/verify", json=_VERIFY_BODY, headers=_auth_headers(owner["access_token"])
        )
        assert still_ok.status_code == 200

    def test_revoking_with_no_prior_acceptance_is_a_safe_noop(self, client):
        owner = _register(client, "owner6@example.com")
        response = client.post(
            "/legal/revoke", json={}, headers=_auth_headers(owner["access_token"])
        )
        assert response.status_code == 200

    def test_revoke_requires_a_valid_token(self, client):
        response = client.post("/legal/revoke", json={})
        assert response.status_code == 401

    def test_revocation_does_not_cross_tenants(self, client):
        owner_a = _register(client, "ownerA@example.com")
        owner_b = _register(client, "ownerB@example.com")
        client.post("/legal/accept", headers=_auth_headers(owner_a["access_token"]))
        client.post("/legal/accept", headers=_auth_headers(owner_b["access_token"]))

        client.post("/legal/revoke", json={}, headers=_auth_headers(owner_a["access_token"]))

        still_ok = client.post(
            "/verification/verify", json=_VERIFY_BODY, headers=_auth_headers(owner_b["access_token"])
        )
        assert still_ok.status_code == 200
