"""Proves the extraction endpoint end-to-end through the real API, and
proves the one property the endpoint exists for: **a caller sees what was
not read before what was**.

Held-out measurement across six states puts coverage between 47% and 79%.
Between a fifth and a half of a real statute comes back unclassified, so a
response that leads with the obligations invites reading them as *the*
obligations. ``test_the_response_leads_with_what_was_not_read`` asserts
the JSON key order directly, because that ordering is the guarantee and
a future refactor that tidies the field order would silently remove it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from legal_engine.api.main import app
from legal_engine.core.config import settings

# Two provisions the taxonomy knows and one it does not, so every
# response below carries both halves.
_MIXED = (
    "Each vacation rental shall provide one off-street parking space. "
    "No dwelling unit may be rented for more than 90 nights in any calendar year. "
    "Every operator shall maintain a valid certificate of insurance at all times."
)

_BODY = {
    "text": _MIXED,
    "citation": "City Code § 12-3",
    "jurisdiction_tier": "municipal",
    "jurisdiction_path": ["United States", "Florida", "City of Example"],
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    with TestClient(app) as c:
        yield c


class TestTheGuaranteeThisEndpointExistsFor:
    def test_the_response_leads_with_what_was_not_read(self, client):
        """Pydantic serialises in declaration order, so this is the
        difference between a caller meeting the gaps first and meeting
        the findings first. Asserted on raw key order rather than on the
        parsed dict, because that is the thing that can regress."""
        response = client.post("/extraction/analyze", json=_BODY)
        assert response.status_code == 200

        keys = list(response.json().keys())
        assert keys.index("unread") < keys.index("obligations")
        assert keys.index("complete") == 0

    def test_an_incomplete_extraction_says_so(self, client):
        body = response = client.post("/extraction/analyze", json=_BODY).json()
        assert body["complete"] is False
        assert body["unread_count"] >= 1
        assert 0.0 < body["coverage"] < 1.0
        assert response is body

    def test_each_abstention_carries_the_work_that_would_fix_it(self, client):
        """The two reason codes are repaired in different places —
        taxonomy versus segmentation — and conflating them is how a
        coverage number improves without the analysis getting better."""
        body = client.post("/extraction/analyze", json=_BODY).json()

        unread = body["unread"]
        assert unread
        for provision in unread:
            assert provision["reason_code"] in {
                "no_subject_match",
                "truncated_fragment",
                "model_declined",
            }
            assert provision["remedy"]
            assert provision["text"]

    def test_triage_counts_by_cause(self, client):
        body = client.post("/extraction/analyze", json=_BODY).json()
        assert sum(body["triage"].values()) == body["unread_count"]


class TestTheObligationsThemselves:
    def test_recognised_provisions_come_back_classified(self, client):
        body = client.post("/extraction/analyze", json=_BODY).json()

        by_text = {o["text"]: o for o in body["obligations"]}
        parking = next(o for t, o in by_text.items() if "parking" in t)
        assert parking["subjects"] == ["parking"]
        assert parking["modality"] == "obligation"

    def test_a_cap_is_not_returned_as_a_licence(self, client):
        """The inversion guard, asserted through the wire rather than in
        a unit test: a night cap read as a permission is the worst
        output this system can produce, and it would look entirely
        ordinary in a JSON response."""
        body = client.post("/extraction/analyze", json=_BODY).json()

        cap = next(o for o in body["obligations"] if "90 nights" in o["text"])
        assert cap["modality"] == "prohibition"

    def test_a_fully_read_provision_reports_complete(self, client):
        body = client.post(
            "/extraction/analyze",
            json={**_BODY, "text": "Each vacation rental shall provide one off-street parking space."},
        ).json()
        assert body["complete"] is True
        assert body["unread"] == []
        assert body["triage"] == {}
        assert body["coverage"] == 1.0


class TestValidation:
    def test_an_unknown_jurisdiction_tier_is_rejected(self, client):
        response = client.post(
            "/extraction/analyze", json={**_BODY, "jurisdiction_tier": "galactic"}
        )
        assert response.status_code == 422


class TestConsentGate:
    def test_extraction_is_gated_like_verification_and_simulation(self, monkeypatch):
        """It produces output a person may act on in a legal context, so
        it sits with the consent-gated routers rather than the merely
        authenticated ones."""
        monkeypatch.setattr(settings, "api_auth_enabled", True)
        with TestClient(app) as client:
            response = client.post("/extraction/analyze", json=_BODY)
        assert response.status_code in {401, 403}
