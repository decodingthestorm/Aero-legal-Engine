"""Proves real, end-to-end cross-tenant data isolation through the actual
FastAPI app — not just at the repository/registry unit-test level (see
tests/unit/test_statute_repository.py, test_sql_repository.py,
test_hydration.py), but through the full request path: JWT ->
get_current_tenant -> TenantIdDep / tenant-scoped GraphServiceDep /
VectorIndexDep -> StatuteRepository.

There's only one configured client credential (settings.api_client_id),
scoped to one tenant (settings.api_client_tenant_id) — there's no
user/tenant registration flow to obtain a second real credential. This
test mints a second token directly via create_token() with a different
tenant_id claim, which is exactly what a second registered client's token
would look like; it exercises the same get_current_tenant dependency and
TenantIndexRegistry every real request goes through, so it genuinely
proves the isolation mechanism rather than assuming it from the unit
tests alone.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from legal_engine.api.main import app
from legal_engine.api.security import create_token
from legal_engine.core.config import settings

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    with TestClient(app) as c:
        yield c


def _auth_headers(tenant_id: str) -> dict[str, str]:
    token = create_token(subject=f"test-client-{tenant_id}", tenant_id=tenant_id)
    return {"Authorization": f"Bearer {token}"}


def _add_statute(client: TestClient, tenant_id: str, citation: str, entity: str) -> str:
    response = client.post(
        "/graph/statutes",
        json={
            "source_type": "municipal_code",
            "jurisdiction_tier": 4,
            "citation": citation,
            "title": citation,
            "text": f"text unique to {citation}",
            "applies_to": [entity],
        },
        headers=_auth_headers(tenant_id),
    )
    assert response.status_code == 200
    return response.json()["id"]


class TestCrossTenantIsolation:
    def test_get_statute_by_id_is_invisible_to_a_different_tenant(self, client):
        statute_id = _add_statute(client, TENANT_A, "Sec. Isolated 1", "entity-iso-1")

        own_tenant = client.get(f"/graph/statutes/{statute_id}", headers=_auth_headers(TENANT_A))
        assert own_tenant.status_code == 200

        other_tenant = client.get(f"/graph/statutes/{statute_id}", headers=_auth_headers(TENANT_B))
        assert other_tenant.status_code == 404

    def test_list_statutes_never_shows_another_tenants_data(self, client):
        _add_statute(client, TENANT_A, "Sec. List-Iso A", "entity-list-iso-a")
        _add_statute(client, TENANT_B, "Sec. List-Iso B", "entity-list-iso-b")

        a_view = client.get("/graph/statutes", headers=_auth_headers(TENANT_A))
        b_view = client.get("/graph/statutes", headers=_auth_headers(TENANT_B))

        a_citations = {s["citation"] for s in a_view.json()}
        b_citations = {s["citation"] for s in b_view.json()}
        assert "Sec. List-Iso A" in a_citations
        assert "Sec. List-Iso B" not in a_citations
        assert "Sec. List-Iso B" in b_citations
        assert "Sec. List-Iso A" not in b_citations

    def test_preemption_resolution_does_not_cross_tenants(self, client):
        """Proves GraphService isolation specifically: tenant A's statute
        governing an entity must not be visible when tenant B asks about
        an entity of the same name — the two tenants' graphs are
        genuinely separate structures (TenantIndexRegistry), not one
        shared graph filtered after the fact."""
        _add_statute(client, TENANT_A, "Sec. Preempt Iso", "shared-entity-name")

        a_view = client.get(
            "/graph/preemption/shared-entity-name", headers=_auth_headers(TENANT_A)
        )
        assert a_view.json()["governing_citation"] == "Sec. Preempt Iso"

        b_view = client.get(
            "/graph/preemption/shared-entity-name", headers=_auth_headers(TENANT_B)
        )
        assert b_view.json()["governing_citation"] is None

    def test_semantic_search_does_not_cross_tenants(self, client):
        """Proves VectorIndex isolation: tenant B's search must not surface
        a statute that only exists in tenant A's index."""
        _add_statute(client, TENANT_A, "Sec. Search Iso", "entity-search-iso")

        b_search = client.post(
            "/graph/search",
            json={"query_text": "text unique to Sec. Search Iso", "top_k": 5},
            headers=_auth_headers(TENANT_B),
        )
        assert b_search.status_code == 200
        assert all(m["citation"] != "Sec. Search Iso" for m in b_search.json())

        a_search = client.post(
            "/graph/search",
            json={"query_text": "text unique to Sec. Search Iso", "top_k": 5},
            headers=_auth_headers(TENANT_A),
        )
        assert any(m["citation"] == "Sec. Search Iso" for m in a_search.json())
