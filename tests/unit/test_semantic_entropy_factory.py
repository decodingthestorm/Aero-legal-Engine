"""Tests uncertainty.factory's dispatch logic.

The case worth pinning here beyond plain backend selection: a
misconfigured entropy threshold must propagate as a construction error,
not be clamped into range. Silently repairing an 8.5 would recreate the
exact defect SemanticEntropyGate's validation exists to prevent — a gate
that reads as configured and can never fire.
"""

import math

import pytest

from legal_engine.core.config import settings
from legal_engine.uncertainty.entailment import LexicalEntailmentModel
from legal_engine.uncertainty.factory import build_entailment_model, build_semantic_entropy_gate


class TestBuildEntailmentModel:
    def test_default_backend_is_lexical(self):
        assert isinstance(build_entailment_model(), LexicalEntailmentModel)

    def test_cross_encoder_backend_fails_closed_with_an_install_hint(self, monkeypatch):
        """sentence-transformers isn't installable in this environment
        (torch's native extensions don't load), so selecting it must
        raise a clear, actionable ImportError rather than silently
        falling back to the weaker lexical model — the same fail-closed
        contract as the KMS/Vault KeySigner backends."""
        monkeypatch.setattr(settings, "entailment_backend", "cross_encoder")
        with pytest.raises(ImportError, match="sentence-transformers"):
            build_entailment_model()


class TestBuildSemanticEntropyGate:
    def test_builds_with_default_settings(self):
        gate = build_semantic_entropy_gate()
        assert gate.max_possible_entropy == pytest.approx(math.log(10))

    def test_default_threshold_is_below_the_ceiling(self):
        """The invariant the shipped defaults have to satisfy: a gate
        built straight from config must actually be able to fire."""
        assert settings.semantic_entropy_threshold < math.log(settings.semantic_entropy_samples)

    def test_accepts_an_injected_model(self):
        model = LexicalEntailmentModel()
        gate = build_semantic_entropy_gate(model=model)
        assert gate.evaluate(["same"] * settings.semantic_entropy_samples).triage_pass is True

    def test_an_unreachable_configured_threshold_raises_rather_than_clamping(self, monkeypatch):
        monkeypatch.setattr(settings, "semantic_entropy_threshold", 8.5)
        with pytest.raises(ValueError, match="cannot fire"):
            build_semantic_entropy_gate()

    def test_sample_count_from_settings_sets_the_ceiling(self, monkeypatch):
        monkeypatch.setattr(settings, "semantic_entropy_samples", 20)
        assert build_semantic_entropy_gate().max_possible_entropy == pytest.approx(math.log(20))
