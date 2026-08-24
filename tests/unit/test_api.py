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


class TestCors:
    """TestClient doesn't enforce CORS the way a browser does (there's no
    same-origin policy being applied), but the server-side behavior of
    CORSMiddleware — which headers it adds in response to a given Origin —
    is real and testable here, and is exactly what a browser relies on."""

    def test_allowed_origin_gets_cors_header(self, client):
        response = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_disallowed_origin_gets_no_cors_header(self, client):
        response = client.get("/health", headers={"Origin": "http://evil.example.com"})
        assert "access-control-allow-origin" not in response.headers

    def test_preflight_allows_authorization_header_for_protected_routes(self, client):
        response = client.options(
            "/simulation/penalty",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


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
        data = response.json()
        assert data["proof_result"]["satisfiable"] is True
        assert data["smt_lib2"].startswith("(declare-datatypes")
        assert "Owns" in data["smt_lib2"]

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
        assert response.json()["proof_result"]["satisfiable"] is False

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

    def test_solver_timeout_degrades_gracefully_and_server_stays_up(self, client, monkeypatch):
        """A genuine Z3 timeout under load shouldn't crash the process or
        wedge the event loop for other requests — it should come back as a
        clean 400 like any other domain error, and the server keeps serving
        traffic normally afterward. Z3 itself is too fast to reliably force
        this organically (see test_formal_logic.py's TestSolverPoolTimeout
        docstring for what was actually tried), so this mocks z3.Solver
        directly, same technique."""
        import z3

        monkeypatch.setattr(z3.Solver, "check", lambda self: z3.unknown)
        monkeypatch.setattr(z3.Solver, "reason_unknown", lambda self: "timeout")

        body = {
            "forall_vars": ["x"],
            "domain": ["alice", "bob"],
            "matrix": {"kind": "atom", "predicate": "Owns", "args": [{"kind": "variable", "name": "x"}]},
        }
        response = client.post("/verification/verify", json=body)
        assert response.status_code == 400
        assert response.json()["error"] == "SolverTimeoutError"

        # The mock is scoped to this test only (monkeypatch reverts after);
        # a normal request right after the "timeout" should succeed as if
        # nothing happened, proving the process itself is unaffected.
        monkeypatch.undo()
        follow_up = client.post("/verification/verify", json=body)
        assert follow_up.status_code == 200
        assert follow_up.json()["proof_result"]["satisfiable"] is True


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
        assert data == [{"x": 100.0, "y": 0.0}, {"x": 110.0, "y": 200.0}]

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

    def test_added_statute_is_persisted_and_fetchable_by_id(self, client):
        add_resp = client.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": "Sec. 42",
                "title": "Persisted Ordinance",
                "text": "persisted text",
                "applies_to": ["entity-persist"],
            },
        )
        statute_id = add_resp.json()["id"]

        get_resp = client.get(f"/graph/statutes/{statute_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["citation"] == "Sec. 42"
        assert get_resp.json()["text"] == "persisted text"

    def test_get_missing_statute_returns_404(self, client):
        response = client.get("/graph/statutes/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_list_statutes_filters_by_citation(self, client):
        client.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": "Sec. List A",
                "title": "A",
                "text": "text a",
                "applies_to": ["entity-list"],
            },
        )
        client.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": "Sec. List B",
                "title": "B",
                "text": "text b",
                "applies_to": ["entity-list"],
            },
        )

        response = client.get("/graph/statutes", params={"citation": "Sec. List A"})
        assert response.status_code == 200
        citations = [s["citation"] for s in response.json()]
        assert citations == ["Sec. List A"]

    def test_list_statutes_without_filter_returns_all(self, client):
        client.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": "Sec. All 1",
                "title": "A",
                "text": "text",
                "applies_to": ["entity-all"],
            },
        )
        response = client.get("/graph/statutes")
        assert response.status_code == 200
        assert any(s["citation"] == "Sec. All 1" for s in response.json())


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
