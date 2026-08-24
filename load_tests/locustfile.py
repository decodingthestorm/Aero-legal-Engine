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

``verify_large_domain_clause`` deliberately does NOT try to trip the 480ms
timeout — an empirical check (see tests/unit/test_formal_logic.py's
TestSolverPoolTimeout docstring) found that Z3's EPR handling is fast
enough that even a domain of 800 elements with 3 quantified variables (a
formula that would need 512M naive ground instantiations) still solved in
~15ms; it isn't doing brute-force grounding, and organically slow EPR
instances are a research-level construction problem, not a quick script.
What a larger domain *does* still exercise, for real: JSON payload/response
size scaling under concurrent load (the SMT-LIB2 response text grows with
domain size — see smt_generator.py — since it declares one datatype
constructor per domain element).
"""

from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, task

_DOMAIN = [f"actor_{i}" for i in range(8)]
_LARGE_DOMAIN = [f"actor_{i}" for i in range(300)]


def _ownership_implies_reporting_body(domain: list[str]) -> dict:
    """forall x. Owns(x) -> Reports(x) over the given domain."""
    return {
        "forall_vars": ["x"],
        "domain": domain,
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
            "/verification/verify",
            json=_ownership_implies_reporting_body(_DOMAIN),
            catch_response=True,
            name="/verification/verify [small domain]",
        ) as response:
            if response.status_code != 200:
                response.failure(f"unexpected status {response.status_code}")
                return
            elapsed_ms = response.json()["proof_result"]["elapsed_ms"]
            # The Z3 timeout budget itself, not the HTTP round-trip time -
            # this is what settings.z3_timeout_ms is actually bounding.
            if elapsed_ms > 480:
                response.failure(f"Z3 solve took {elapsed_ms:.0f}ms, over the 480ms budget")

    @task(1)
    def verify_large_domain_clause(self):
        """Not expected to approach the timeout (see module docstring) -
        this exercises response payload size under load instead: a
        300-element domain means smt_lib2 declares 300 datatype
        constructors, a meaningfully larger response body than the
        small-domain task's."""
        with self.client.post(
            "/verification/verify",
            json=_ownership_implies_reporting_body(_LARGE_DOMAIN),
            catch_response=True,
            name="/verification/verify [large domain]",
        ) as response:
            if response.status_code != 200:
                response.failure(f"unexpected status {response.status_code}")

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
