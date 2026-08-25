"""Covers api/middleware.py's two behaviours.

Found by audit rather than by design: the correlation-ID header had one
assertion in test_api.py, and the ``LegalEngineError`` handler — which
decides what a client sees whenever a *domain* error escapes a route —
had none at all. Routes deliberately don't catch these
(api/routes/verification.py has no except clause), so this handler is the
only thing standing between a raised NotEPRFragmentError and a 500.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from legal_engine.api.main import app

# An empty domain of discourse fails the EPR decidability check inside
# formal_logic/, which raises NotEPRFragmentError from *inside* the route.
_UNDECIDABLE_BODY = {
    "forall_vars": ["x"],
    "domain": [],
    "matrix": {"kind": "atom", "predicate": "Owns", "args": [{"kind": "variable", "name": "x"}]},
}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class TestDomainErrorHandler:
    def test_a_domain_error_becomes_a_400_not_a_500(self, client):
        """The distinction that matters to a caller: "your formula is
        outside the decidable fragment" is a client error, not a server
        fault."""
        response = client.post("/verification/verify", json=_UNDECIDABLE_BODY)
        assert response.status_code == 400

    def test_the_response_names_the_exception_class(self, client):
        """So a client can branch on the kind of failure rather than
        string-matching the message."""
        body = client.post("/verification/verify", json=_UNDECIDABLE_BODY).json()
        assert body["error"] == "NotEPRFragmentError"

    def test_the_response_carries_the_actual_reason(self, client):
        body = client.post("/verification/verify", json=_UNDECIDABLE_BODY).json()
        assert "decidability" in body["detail"]

    def test_the_error_body_carries_the_correlation_id(self, client):
        """This is the whole point of pairing the two: an error a user
        reports can be found in the logs by the id they were shown."""
        response = client.post(
            "/verification/verify",
            json=_UNDECIDABLE_BODY,
            headers={"X-Correlation-ID": "trace-me-42"},
        )
        assert response.json()["correlation_id"] == "trace-me-42"


class TestCorrelationId:
    def test_a_supplied_id_is_echoed_back(self, client):
        response = client.get("/health", headers={"X-Correlation-ID": "caller-supplied"})
        assert response.headers["X-Correlation-ID"] == "caller-supplied"

    def test_one_is_generated_when_the_caller_supplies_none(self, client):
        response = client.get("/health")
        UUID(response.headers["X-Correlation-ID"])  # raises if not a well-formed uuid

    def test_each_request_without_one_gets_a_distinct_id(self, client):
        first = client.get("/health").headers["X-Correlation-ID"]
        second = client.get("/health").headers["X-Correlation-ID"]
        assert first != second

    def test_the_header_is_present_on_error_responses_too(self, client):
        """A correlation id that vanished exactly when something went
        wrong would be useless."""
        response = client.post(
            "/verification/verify",
            json=_UNDECIDABLE_BODY,
            headers={"X-Correlation-ID": "still-here"},
        )
        assert response.status_code == 400
        assert response.headers["X-Correlation-ID"] == "still-here"

    def test_the_header_and_the_body_agree(self, client):
        response = client.post("/verification/verify", json=_UNDECIDABLE_BODY)
        assert response.headers["X-Correlation-ID"] == response.json()["correlation_id"]
