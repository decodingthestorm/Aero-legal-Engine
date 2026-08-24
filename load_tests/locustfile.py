"""Load test scenarios against the FastAPI gateway.

Run with the API already up (`uvicorn legal_engine.api.main:app`) and:

    locust -f load_tests/locustfile.py --host http://localhost:8000

or headless, e.g. 20 users ramping up at 5/s for 60 seconds:

    locust -f load_tests/locustfile.py --host http://localhost:8000 \
        --headless -u 20 -r 5 -t 60s --csv load_tests/results/run

Task weights approximate a realistic mix: /verification/verify is the
heaviest endpoint (routes through the Z3 solver pool, bounded to
settings.z3_pool_size concurrent solves and a settings.z3_timeout_ms=480ms
budget per solve) and gets proportionally more traffic, since it's the one
most likely to reveal a concurrency bottleneck the others won't.
"""

from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, task

_DOMAIN = [f"actor_{i}" for i in range(8)]


def _verify_clause_body() -> dict:
    """forall x. Owns(x) -> Reports(x) over an 8-element domain — small
    enough to solve quickly, large enough to be a non-trivial EPR check."""
    return {
        "forall_vars": ["x"],
        "domain": _DOMAIN,
        "matrix": {
            "kind": "implies",
            "antecedent": {"kind": "atom", "predicate": "Owns", "args": [{"kind": "variable", "name": "x"}]},
            "consequent": {
                "kind": "atom",
                "predicate": "Reports",
                "args": [{"kind": "variable", "name": "x"}],
            },
        },
    }


class GatewayUser(HttpUser):
    wait_time = between(0.1, 1.0)

    @task(3)
    def verify_clause(self):
        with self.client.post(
            "/verification/verify", json=_verify_clause_body(), catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"unexpected status {response.status_code}")
                return
            elapsed_ms = response.json()["proof_result"]["elapsed_ms"]
            # The Z3 timeout budget itself, not the HTTP round-trip time -
            # this is what settings.z3_timeout_ms is actually bounding.
            if elapsed_ms > 480:
                response.failure(f"Z3 solve took {elapsed_ms:.0f}ms, over the 480ms budget")

    @task(2)
    def compute_penalty(self):
        self.client.post(
            "/simulation/penalty",
            json={"benefit": 1000, "cost_compliance": 50, "p_detect": 0.3},
            name="/simulation/penalty",
        )

    @task(2)
    def add_and_search_statute(self):
        citation = f"Sec. LT-{uuid.uuid4().hex[:8]}"
        self.client.post(
            "/graph/statutes",
            json={
                "source_type": "municipal_code",
                "jurisdiction_tier": 4,
                "citation": citation,
                "title": "Load Test Ordinance",
                "text": "No person shall operate a short-term rental without a permit.",
                "applies_to": [f"entity_{random.randint(0, 50)}"],
            },
            name="/graph/statutes [POST]",
        )
        self.client.post(
            "/graph/search",
            json={"query_text": "short-term rental permit", "top_k": 5},
            name="/graph/search",
        )

    @task(1)
    def detect_loopholes(self):
        self.client.post(
            "/refactoring/detect-loopholes",
            json={
                "edges": [
                    {"source": "shell_a", "target": "shell_b", "weight": -3.0},
                    {"source": "shell_b", "target": "shell_a", "weight": 1.0},
                ]
            },
            name="/refactoring/detect-loopholes",
        )

    @task(1)
    def health(self):
        self.client.get("/health", name="/health")
