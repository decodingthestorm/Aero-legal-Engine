"""Proves tenant member management end-to-end through the real API:
listing a tenant's roster, changing roles, and removing a member, plus
the one real invariant this feature has to protect — a tenant can never
end up with zero owners.
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


def _invite_and_accept(client: TestClient, owner_tokens: dict, email: str) -> dict:
    invite_token = client.post(
        "/auth/invite", json={"email": email}, headers=_auth_headers(owner_tokens["access_token"])
    ).json()["invite_token"]
    response = client.post(
        "/auth/accept-invite", json={"invite_token": invite_token, "password": "correct horse battery"}
    )
    assert response.status_code == 200
    return response.json()


def _protected_request(client: TestClient, access_token: str):
    return client.get("/graph/statutes", headers=_auth_headers(access_token))


class TestListMembers:
    def test_owner_sees_both_themselves_and_an_invited_member(self, client):
        owner = _register(client, "owner1@example.com")
        _invite_and_accept(client, owner, "member1@example.com")

        response = client.get("/auth/members", headers=_auth_headers(owner["access_token"]))
        assert response.status_code == 200
        emails = {m["email"] for m in response.json()["members"]}
        assert emails == {"owner1@example.com", "member1@example.com"}

    def test_a_plain_member_can_also_list_the_roster(self, client):
        owner = _register(client, "owner2@example.com")
        member = _invite_and_accept(client, owner, "member2@example.com")

        response = client.get("/auth/members", headers=_auth_headers(member["access_token"]))
        assert response.status_code == 200
        assert len(response.json()["members"]) == 2

    def test_listing_requires_authentication(self, client):
        response = client.get("/auth/members")
        assert response.status_code == 401

    def test_member_entries_never_include_the_password_hash(self, client):
        owner = _register(client, "owner3@example.com")
        response = client.get("/auth/members", headers=_auth_headers(owner["access_token"]))
        [entry] = response.json()["members"]
        assert "password_hash" not in entry


class TestChangeRole:
    def test_owner_can_promote_a_member(self, client):
        owner = _register(client, "owner4@example.com")
        _invite_and_accept(client, owner, "member4@example.com")

        response = client.post(
            "/auth/members/member4@example.com/role",
            json={"role": "owner"},
            headers=_auth_headers(owner["access_token"]),
        )
        assert response.status_code == 200
        assert response.json()["role"] == "owner"

    def test_promoted_member_can_now_manage_members_themselves(self, client):
        owner = _register(client, "owner5@example.com")
        member = _invite_and_accept(client, owner, "member5@example.com")
        client.post(
            "/auth/members/member5@example.com/role",
            json={"role": "owner"},
            headers=_auth_headers(owner["access_token"]),
        )

        response = client.post(
            "/auth/invite",
            json={"email": "newperson@example.com"},
            headers=_auth_headers(member["access_token"]),
        )
        assert response.status_code == 200

    def test_a_plain_member_cannot_change_roles(self, client):
        owner = _register(client, "owner6@example.com")
        member = _invite_and_accept(client, owner, "member6@example.com")

        response = client.post(
            "/auth/members/owner6@example.com/role",
            json={"role": "member"},
            headers=_auth_headers(member["access_token"]),
        )
        assert response.status_code == 403

    def test_cannot_demote_the_last_remaining_owner(self, client):
        owner = _register(client, "owner7@example.com")
        _invite_and_accept(client, owner, "member7@example.com")

        response = client.post(
            "/auth/members/owner7@example.com/role",
            json={"role": "member"},
            headers=_auth_headers(owner["access_token"]),
        )
        assert response.status_code == 409

    def test_demoting_an_owner_is_fine_when_another_owner_remains(self, client):
        owner = _register(client, "owner8@example.com")
        member = _invite_and_accept(client, owner, "member8@example.com")
        client.post(
            "/auth/members/member8@example.com/role",
            json={"role": "owner"},
            headers=_auth_headers(owner["access_token"]),
        )

        response = client.post(
            "/auth/members/owner8@example.com/role",
            json={"role": "member"},
            headers=_auth_headers(member["access_token"]),
        )
        assert response.status_code == 200

    def test_changing_role_of_a_member_in_a_different_tenant_is_404(self, client):
        owner_a = _register(client, "ownerA@example.com")
        _register(client, "ownerB@example.com")

        response = client.post(
            "/auth/members/ownerB@example.com/role",
            json={"role": "member"},
            headers=_auth_headers(owner_a["access_token"]),
        )
        assert response.status_code == 404


class TestRemoveMember:
    def test_owner_can_remove_a_member(self, client):
        owner = _register(client, "owner9@example.com")
        _invite_and_accept(client, owner, "member9@example.com")

        response = client.delete(
            "/auth/members/member9@example.com", headers=_auth_headers(owner["access_token"])
        )
        assert response.status_code == 200
        assert response.json()["removed"] is True

        roster = client.get("/auth/members", headers=_auth_headers(owner["access_token"])).json()
        assert "member9@example.com" not in {m["email"] for m in roster["members"]}

    def test_removed_members_active_session_is_immediately_rejected(self, client):
        owner = _register(client, "owner10@example.com")
        member = _invite_and_accept(client, owner, "member10@example.com")
        assert _protected_request(client, member["access_token"]).status_code == 200

        client.delete("/auth/members/member10@example.com", headers=_auth_headers(owner["access_token"]))

        assert _protected_request(client, member["access_token"]).status_code == 401

    def test_a_plain_member_cannot_remove_anyone(self, client):
        owner = _register(client, "owner11@example.com")
        member = _invite_and_accept(client, owner, "member11@example.com")

        response = client.delete(
            "/auth/members/owner11@example.com", headers=_auth_headers(member["access_token"])
        )
        assert response.status_code == 403

    def test_cannot_remove_the_last_remaining_owner(self, client):
        owner = _register(client, "owner12@example.com")
        _invite_and_accept(client, owner, "member12@example.com")

        response = client.delete(
            "/auth/members/owner12@example.com", headers=_auth_headers(owner["access_token"])
        )
        assert response.status_code == 409

    def test_removing_a_member_in_a_different_tenant_is_404(self, client):
        owner_a = _register(client, "ownerC@example.com")
        _register(client, "ownerD@example.com")

        response = client.delete(
            "/auth/members/ownerD@example.com", headers=_auth_headers(owner_a["access_token"])
        )
        assert response.status_code == 404
