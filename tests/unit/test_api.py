import httpx
import pytest
from fastapi.testclient import TestClient

from legal_engine.api.dependencies import get_fetcher
from legal_engine.api.main import app
from legal_engine.ingestion.rate_limiter import PoliteFetcher


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class TestHealth:
    def test_health_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestVerificationRoute:
    def test_verify_satisfiable_formula(self, client):
        body = {
            "forall_vars": ["x"],
            "domain": ["alice", "bob"],
            "matrix": {
                "kind": "implies",
                "antecedent": {"kind": "atom", "predicate": "Owns", "args": [{"kind": "variable", "name": "x"}]},
                "consequent": {"kind": "atom", "predicate": "Reports", "args": [{"kind": "variable", "name": "x"}]},
            },
        }
        response = client.post("/verification/verify", json=body)
        assert response.status_code == 200
        assert response.json()["satisfiable"] is True

    def test_verify_unsatisfiable_formula(self, client):
        body = {
            "forall_vars": ["x"],
            "domain": ["alice", "bob"],
            "matrix": {
                "kind": "and",
                "operands": [
                    {
                        "kind": "implies",
                        "antecedent": {"kind": "atom", "predicate": "Owns", "args": [{"kind": "variable", "name": "x"}]},
                        "consequent": {"kind": "atom", "predicate": "Reports", "args": [{"kind": "variable", "name": "x"}]},
                    },
                    {"kind": "atom", "predicate": "Owns", "args": [{"kind": "constant", "name": "alice"}]},
                    {"kind": "not", "operand": {"kind": "atom", "predicate": "Reports", "args": [{"kind": "constant", "name": "alice"}]}},
                ],
            },
        }
        response = client.post("/verification/verify", json=body)
        assert response.status_code == 200
        assert response.json()["satisfiable"] is False

    def test_verify_rejects_unbound_variable_with_400(self, client):
        body = {
            "forall_vars": ["x"],
            "domain": ["alice"],
            "matrix": {"kind": "atom", "predicate": "Owns", "args": [{"kind": "variable", "name": "y"}]},
        }
        response = client.post("/verification/verify", json=body)
        assert response.status_code == 400
        assert response.json()["error"] == "NotEPRFragmentError"
        assert "X-Correlation-ID" in response.headers

    def test_verify_rejects_empty_domain_with_422(self, client):
        body = {"matrix": {"kind": "atom", "predicate": "P", "args": []}, "domain": []}
        response = client.post("/verification/verify", json=body)
        # domain=[] passes FastAPI validation (it's a valid empty list) but
        # fails compile_epr_formula's own check -> our 400 handler, not 422.
        assert response.status_code == 400


class TestSimulationRoutes:
    def test_compute_penalty(self, client):
        response = client.post(
            "/simulation/penalty", json={"benefit": 1000, "cost_compliance": 50, "p_detect": 0.3}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["recommended_penalty_is_dominant"] is True
        assert data["recommended_penalty"] > data["minimum_deterrent_penalty"]

    def test_compute_penalty_curve(self, client):
        response = client.post(
            "/simulation/penalty-curve",
            json={"k": 2.0, "x_limit": 100.0, "sample_points": [100.0, 110.0]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["100.0"] == 0.0
        assert data["110.0"] == 200.0

    def test_trembling_hand(self, client):
        response = client.post(
            "/simulation/trembling-hand",
            json={
                "actor_id": "landlord-1",
                "candidate_strategy": "comply",
                "payoff_matrix": {
                    "payoffs": {"landlord-1": {"comply": -50.0, "exploit": -75.0, "evade": -200.0}}
                },
                "epsilon_max": 0.05,
            },
        )
        assert response.status_code == 200
        assert response.json()["is_perfect"] is True


class TestRefactoringRoute:
    def test_detect_loopholes(self, client):
        body = {
            "edges": [
                {"source": "shell_co_a", "target": "shell_co_b", "weight": -3.0},
                {"source": "shell_co_b", "target": "shell_co_a", "weight": 1.0},
            ]
        }
        response = client.post("/refactoring/detect-loopholes", json=body)
        assert response.status_code == 200
        data = response.json()
        assert len(data["loopholes"]) == 1
        assert data["loopholes"][0]["total_weight"] == pytest.approx(-2.0)
        assert data["corrections"]["shell_co_a->shell_co_b"] == pytest.approx(1.0)


class TestGraphRoutes:
    def test_add_statute_and_resolve_preemption(self, client):
        state_resp = client.post(
            "/graph/statutes",
            json={
                "source_type": "state_statute",
                "jurisdiction_tier": 2,
                "citation": "State 65.850",
                "title": "STR permit",
                "text": "short-term rentals allowed with a state permit",
                "applies_to": ["str-regulation"],
            },
        )
        assert state_resp.status_code == 200

        muni_resp = client.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": "Muni 12.04",
                "title": "STR ban",
                "text": "short-term rentals banned",
                "applies_to": ["str-regulation"],
            },
        )
        assert muni_resp.status_code == 200

        preemption_resp = client.get("/graph/preemption/str-regulation")
        assert preemption_resp.status_code == 200
        data = preemption_resp.json()
        assert data["governing_citation"] == "State 65.850"
        assert data["preempted_citations"] == ["Muni 12.04"]
        assert data["requires_review"] is False

    def test_preemption_for_unknown_entity(self, client):
        response = client.get("/graph/preemption/does-not-exist")
        assert response.status_code == 200
        assert response.json()["governing_citation"] is None

    def test_search_statutes(self, client):
        client.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": "Sec. 99",
                "title": "Zoning",
                "text": "short-term rental permits required in residential zones",
                "applies_to": ["entity-x"],
            },
        )
        response = client.post("/graph/search", json={"query_text": "short-term rental permit", "top_k": 3})
        assert response.status_code == 200
        assert any(m["citation"] == "Sec. 99" for m in response.json())


class TestIngestionRoute:
    def test_run_ingestion_job_with_mocked_fetcher(self, client):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text='<article class="ordinance" data-citation="Sec. 1" data-title="A">'
                '<div class="ordinance-text">Text</div></article>',
            )

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        mock_fetcher = PoliteFetcher(client=mock_client, min_delay_seconds=0, respect_robots_txt=False)

        app.dependency_overrides[get_fetcher] = lambda: mock_fetcher
        try:
            response = client.post(
                "/ingestion/jobs", json={"url": "https://example.gov/x", "source_type": "municipal_code"}
            )
        finally:
            app.dependency_overrides.pop(get_fetcher, None)

        assert response.status_code == 200
        assert response.json()[0]["citation"] == "Sec. 1"
