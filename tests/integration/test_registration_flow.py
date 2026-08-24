"""Proves self-service registration end-to-end through the real API:
POST /auth/register provisions a real, independent tenant + user, the
issued access token actually works on a protected route, two separate
registrations get two fully isolated tenants (reusing the same
data-isolation guarantee tests/integration/test_multi_tenant_isolation.py
already proves for directly-minted tokens — this proves it holds for
tokens obtained the real way, through registration), and the pre-existing
demo credential keeps working unconditionally alongside real accounts.
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


class TestRegistration:
    def test_register_returns_a_new_tenant_and_working_tokens(self, client):
        response = client.post(
            "/auth/register", json={"email": "alice@example.com", "password": "correct horse battery"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"].startswith("tenant-")
        assert data["access_token"]
        assert data["refresh_token"]

        headers = {"Authorization": f"Bearer {data['access_token']}"}
        add_resp = client.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": "Sec. Registered",
                "title": "Registered Ordinance",
                "text": "text",
                "applies_to": ["entity-registered"],
            },
            headers=headers,
        )
        assert add_resp.status_code == 200

    def test_duplicate_email_is_rejected(self, client):
        body = {"email": "bob@example.com", "password": "correct horse battery"}
        first = client.post("/auth/register", json=body)
        assert first.status_code == 200

        second = client.post("/auth/register", json=body)
        assert second.status_code == 409

    def test_registered_user_can_log_in_via_auth_token(self, client):
        client.post(
            "/auth/register", json={"email": "carol@example.com", "password": "correct horse battery"}
        )

        login = client.post(
            "/auth/token", json={"client_id": "carol@example.com", "client_secret": "correct horse battery"}
        )
        assert login.status_code == 200
        assert login.json()["access_token"]

    def test_wrong_password_is_rejected(self, client):
        client.post(
            "/auth/register", json={"email": "dave@example.com", "password": "correct horse battery"}
        )

        login = client.post(
            "/auth/token", json={"client_id": "dave@example.com", "client_secret": "wrong password"}
        )
        assert login.status_code == 401

    def test_demo_credential_still_works_alongside_real_accounts(self, client):
        client.post(
            "/auth/register", json={"email": "erin@example.com", "password": "correct horse battery"}
        )

        demo_login = client.post(
            "/auth/token",
            json={"client_id": settings.api_client_id, "client_secret": settings.api_client_secret},
        )
        assert demo_login.status_code == 200

    def test_two_registrations_get_fully_isolated_tenants(self, client):
        first = client.post(
            "/auth/register", json={"email": "frank@example.com", "password": "correct horse battery"}
        ).json()
        second = client.post(
            "/auth/register", json={"email": "grace@example.com", "password": "correct horse battery"}
        ).json()
        assert first["tenant_id"] != second["tenant_id"]

        first_headers = {"Authorization": f"Bearer {first['access_token']}"}
        second_headers = {"Authorization": f"Bearer {second['access_token']}"}

        client.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": "Sec. Frank Only",
                "title": "A",
                "text": "text",
                "applies_to": ["entity-frank"],
            },
            headers=first_headers,
        )

        second_view = client.get("/graph/statutes", headers=second_headers)
        citations = {s["citation"] for s in second_view.json()}
        assert "Sec. Frank Only" not in citations

    def test_invalid_email_shape_is_rejected(self, client):
        response = client.post(
            "/auth/register", json={"email": "not-an-email", "password": "correct horse battery"}
        )
        assert response.status_code == 422

    def test_short_password_is_rejected(self, client):
        response = client.post("/auth/register", json={"email": "henry@example.com", "password": "short"})
        assert response.status_code == 422
