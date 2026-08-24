"""Exercises the API's optional JWT auth layer. Every other API test runs
with auth off (the default) — this file specifically flips it on."""

import pytest
from fastapi.testclient import TestClient

from legal_engine.api.main import app
from legal_engine.core.config import settings


@pytest.fixture
def auth_enabled_client(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    with TestClient(app) as c:
        yield c


class TestAuthDisabledByDefault:
    def test_protected_route_works_without_a_token(self):
        with TestClient(app) as client:
            response = client.post(
                "/simulation/penalty", json={"benefit": 100, "cost_compliance": 10, "p_detect": 0.3}
            )
        assert response.status_code == 200


class TestAuthEnabled:
    def test_protected_route_rejects_missing_token(self, auth_enabled_client):
        response = auth_enabled_client.post(
            "/simulation/penalty", json={"benefit": 100, "cost_compliance": 10, "p_detect": 0.3}
        )
        assert response.status_code == 401

    def test_token_issuance_rejects_wrong_credentials(self, auth_enabled_client):
        response = auth_enabled_client.post(
            "/auth/token", json={"client_id": "demo", "client_secret": "wrong"}
        )
        assert response.status_code == 401

    def test_token_issuance_and_authenticated_request(self, auth_enabled_client):
        token_response = auth_enabled_client.post(
            "/auth/token",
            json={"client_id": settings.api_client_id, "client_secret": settings.api_client_secret},
        )
        assert token_response.status_code == 200
        token = token_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # /simulation is also gated on liability-disclaimer acceptance (see
        # tests/integration/test_legal_consent_gate.py for that gate's own
        # dedicated coverage) — accepting it here reflects the real
        # authenticated flow this test is otherwise proving out.
        accept_response = auth_enabled_client.post("/legal/accept", headers=headers)
        assert accept_response.status_code == 200

        response = auth_enabled_client.post(
            "/simulation/penalty",
            json={"benefit": 100, "cost_compliance": 10, "p_detect": 0.3},
            headers=headers,
        )
        assert response.status_code == 200

    def test_garbage_bearer_token_is_rejected(self, auth_enabled_client):
        response = auth_enabled_client.post(
            "/simulation/penalty",
            json={"benefit": 100, "cost_compliance": 10, "p_detect": 0.3},
            headers={"Authorization": "Bearer garbage"},
        )
        assert response.status_code == 401

    def test_health_stays_unprotected(self, auth_enabled_client):
        assert auth_enabled_client.get("/health").status_code == 200
