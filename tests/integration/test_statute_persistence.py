"""Proves statute persistence survives an API restart end-to-end: through
the real FastAPI lifespan (not just SqlAlchemyStatuteRepository in
isolation, which tests/unit/test_sql_repository.py already covers), using
the "sql" statute_backend pointed at a SQLite file standing in for
Postgres — there's no Postgres available to test against for real in this
environment (see tests/integration/test_postgres_repository.py, gated
behind CI's `postgres` service container, for that).

Also proves persistence/hydration.py's startup rehydration: the graph and
vector indexes are in-memory by default (separate settings from
statute_backend — see core/config.py) and would otherwise wake up empty on
every restart even with a durable statute repository behind them.

Re-entering `TestClient(app)`'s context manager on the same `app` object
re-runs its lifespan from scratch each time, which is what simulates two
separate process lifetimes here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from legal_engine.api.main import app
from legal_engine.core.config import settings


def test_statute_and_graph_state_survive_a_simulated_api_restart(tmp_path, monkeypatch):
    dsn = f"sqlite+aiosqlite:///{tmp_path}/persistence_e2e.db"
    monkeypatch.setattr(settings, "statute_backend", "sql")
    monkeypatch.setattr(settings, "postgres_dsn", dsn)

    with TestClient(app) as first_run:
        add_response = first_run.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": "Sec. Durable",
                "title": "Durable Ordinance",
                "text": "this should survive a restart",
                "applies_to": ["durability-check"],
            },
        )
        assert add_response.status_code == 200
        statute_id = add_response.json()["id"]

        # Confirm it resolves *before* any restart, as a baseline.
        preemption_response = first_run.get("/graph/preemption/durability-check")
        assert preemption_response.json()["governing_citation"] == "Sec. Durable"

    # `first_run`'s lifespan has now torn down (engine disposed). A fresh
    # TestClient context on the same `app` re-runs the lifespan from
    # scratch — a new SqlAlchemyStatuteRepository pointed at the same file,
    # standing in for a real process restart. graph_service/vector_index
    # are freshly-constructed in-memory defaults each time (their own
    # settings default to in-memory regardless of statute_backend) — this
    # is exactly the case persistence/hydration.py exists for.
    with TestClient(app) as second_run:
        get_response = second_run.get(f"/graph/statutes/{statute_id}")
        assert get_response.status_code == 200
        assert get_response.json()["citation"] == "Sec. Durable"
        assert get_response.json()["text"] == "this should survive a restart"

        # The statute itself survived via the SQL repository; the graph
        # edge to "durability-check" only survives because hydrate_indexes
        # rebuilt it from the repository's persisted `applies_to` at
        # startup — without that, this would incorrectly show no governing
        # statute despite one being durably on record.
        preemption_response = second_run.get("/graph/preemption/durability-check")
        assert preemption_response.json()["governing_citation"] == "Sec. Durable"

        # Semantic search was rebuilt too.
        search_response = second_run.post(
            "/graph/search", json={"query_text": "this should survive a restart", "top_k": 5}
        )
        assert any(m["citation"] == "Sec. Durable" for m in search_response.json())
