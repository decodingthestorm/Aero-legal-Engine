"""Proves tenant invites end-to-end through the real API: an owner
invites an email, the invitee accepts and lands in the *same* tenant as
the owner (the "join an existing tenant" case /auth/register can't do,
since it always creates a brand-new one), invited users are "member" and
can't send further invites, and an invite token is single-use.
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


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


class TestInviteFlow:
    def test_owner_can_invite_and_invitee_joins_the_same_tenant(self, client):
        owner = _register(client, "owner@example.com")

        invite_resp = client.post(
            "/auth/invite", json={"email": "member@example.com"}, headers=_auth_headers(owner["access_token"])
        )
        assert invite_resp.status_code == 200
        invite_token = invite_resp.json()["invite_token"]

        accept_resp = client.post(
            "/auth/accept-invite", json={"invite_token": invite_token, "password": "correct horse battery"}
        )
        assert accept_resp.status_code == 200
        accepted = accept_resp.json()

        assert accepted["tenant_id"] == owner["tenant_id"]

    def test_invited_member_can_use_the_shared_tenants_data(self, client):
        owner = _register(client, "owner2@example.com")
        invite_token = client.post(
            "/auth/invite", json={"email": "teammate@example.com"}, headers=_auth_headers(owner["access_token"])
        ).json()["invite_token"]
        member = client.post(
            "/auth/accept-invite", json={"invite_token": invite_token, "password": "correct horse battery"}
        ).json()

        add_resp = client.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": "Sec. Owner Added",
                "title": "A",
                "text": "text",
                "applies_to": ["entity-shared"],
            },
            headers=_auth_headers(owner["access_token"]),
        )
        assert add_resp.status_code == 200

        member_view = client.get("/graph/statutes", headers=_auth_headers(member["access_token"]))
        citations = {s["citation"] for s in member_view.json()}
        assert "Sec. Owner Added" in citations

    def test_a_member_cannot_send_invites(self, client):
        owner = _register(client, "owner3@example.com")
        invite_token = client.post(
            "/auth/invite", json={"email": "member3@example.com"}, headers=_auth_headers(owner["access_token"])
        ).json()["invite_token"]
        member = client.post(
            "/auth/accept-invite", json={"invite_token": invite_token, "password": "correct horse battery"}
        ).json()

        response = client.post(
            "/auth/invite",
            json={"email": "someone-else@example.com"},
            headers=_auth_headers(member["access_token"]),
        )
        assert response.status_code == 403

    def test_inviting_an_already_registered_email_is_rejected(self, client):
        owner = _register(client, "owner4@example.com")
        _register(client, "existing@example.com")

        response = client.post(
            "/auth/invite", json={"email": "existing@example.com"}, headers=_auth_headers(owner["access_token"])
        )
        assert response.status_code == 409

    def test_invite_token_is_single_use(self, client):
        owner = _register(client, "owner5@example.com")
        invite_token = client.post(
            "/auth/invite", json={"email": "onceonly@example.com"}, headers=_auth_headers(owner["access_token"])
        ).json()["invite_token"]

        first = client.post(
            "/auth/accept-invite", json={"invite_token": invite_token, "password": "correct horse battery"}
        )
        assert first.status_code == 200

        second = client.post(
            "/auth/accept-invite", json={"invite_token": invite_token, "password": "different password"}
        )
        assert second.status_code == 401

    def test_accepting_with_an_access_token_instead_of_an_invite_token_is_rejected(self, client):
        owner = _register(client, "owner6@example.com")
        response = client.post(
            "/auth/accept-invite",
            json={"invite_token": owner["access_token"], "password": "correct horse battery"},
        )
        assert response.status_code == 401

    def test_invite_requires_authentication(self, client):
        response = client.post("/auth/invite", json={"email": "nobody@example.com"})
        assert response.status_code == 401
