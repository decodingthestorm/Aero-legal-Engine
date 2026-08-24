"""Proves the liability-disclaimer gate end-to-end through the real API:
verification/simulation require an on-record acceptance once auth is
enabled, POST /legal/accept records one (using the token's own subject
claim, not anything client-supplied), and acceptance is tenant-scoped —
one tenant accepting never unblocks another, same isolation guarantee as
tests/integration/test_multi_tenant_isolation.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from legal_engine.api.main import app
from legal_engine.api.security import create_token
from legal_engine.compliance.consent import DISCLAIMER_VERSION
from legal_engine.core.config import settings

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"

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


def _auth_headers(tenant_id: str) -> dict[str, str]:
    token = create_token(subject=f"test-client-{tenant_id}", tenant_id=tenant_id)
    return {"Authorization": f"Bearer {token}"}


class TestDisclaimerIsReadableWithoutAuth:
    def test_get_disclaimer_requires_no_token(self, client):
        response = client.get("/legal/disclaimer")
        assert response.status_code == 200
        assert response.json()["version"] == DISCLAIMER_VERSION
        assert "do not constitute legal advice" in response.json()["text"]


class TestConsentGate:
    def test_verification_is_blocked_without_acceptance(self, client):
        response = client.post("/verification/verify", json=_VERIFY_BODY, headers=_auth_headers(TENANT_A))
        assert response.status_code == 403
        assert "disclaimer" in response.json()["detail"].lower()

    def test_simulation_is_blocked_without_acceptance(self, client):
        response = client.post("/simulation/penalty", json=_PENALTY_BODY, headers=_auth_headers(TENANT_A))
        assert response.status_code == 403

    def test_accepting_unblocks_verification_and_simulation(self, client):
        accept = client.post("/legal/accept", headers=_auth_headers(TENANT_A))
        assert accept.status_code == 200
        assert accept.json() == {
            "tenant_id": TENANT_A,
            "disclaimer_version": DISCLAIMER_VERSION,
            "already_accepted": False,
        }

        verify_resp = client.post("/verification/verify", json=_VERIFY_BODY, headers=_auth_headers(TENANT_A))
        assert verify_resp.status_code == 200

        sim_resp = client.post("/simulation/penalty", json=_PENALTY_BODY, headers=_auth_headers(TENANT_A))
        assert sim_resp.status_code == 200

    def test_accepting_twice_reports_already_accepted(self, client):
        client.post("/legal/accept", headers=_auth_headers(TENANT_A))
        second = client.post("/legal/accept", headers=_auth_headers(TENANT_A))
        assert second.json()["already_accepted"] is True

    def test_other_routers_are_unaffected_by_the_consent_gate(self, client):
        """refactoring/graph/ingestion aren't what the disclaimer text is
        about (formal verification, game-theoretic modeling) — they stay
        gated by require_auth alone, same as before this feature."""
        response = client.get("/graph/statutes", headers=_auth_headers(TENANT_A))
        assert response.status_code == 200

    def test_acceptance_does_not_cross_tenants(self, client):
        client.post("/legal/accept", headers=_auth_headers(TENANT_A))

        still_blocked = client.post(
            "/verification/verify", json=_VERIFY_BODY, headers=_auth_headers(TENANT_B)
        )
        assert still_blocked.status_code == 403

    def test_accept_requires_a_valid_token(self, client):
        response = client.post("/legal/accept")
        assert response.status_code == 401
