"""Settings-driven construction of the entailment backend and the
semantic-entropy gate, mirroring knowledge_graph/factory.py and
core/email_sender_factory.py: callers ask for a gate, not for a specific
backend.

``build_semantic_entropy_gate`` deliberately does no threshold clamping
or coercion of its own — it passes settings straight through and lets
``SemanticEntropyGate.__init__`` reject an unfireable threshold. Silently
clamping a misconfigured 8.5 down to something valid would restore the
exact failure mode the validation exists to prevent: a gate that looks
configured and is not.
"""

from __future__ import annotations

from legal_engine.core.config import settings
from legal_engine.uncertainty.entailment import (
    CrossEncoderEntailmentModel,
    EntailmentModel,
    LexicalEntailmentModel,
)
from legal_engine.uncertainty.semantic_entropy import SemanticEntropyGate


def build_entailment_model() -> EntailmentModel:
    if settings.entailment_backend == "cross_encoder":
        return CrossEncoderEntailmentModel(
            model_name=settings.entailment_model_name,
            entailment_label_index=settings.entailment_label_index,
        )
    return LexicalEntailmentModel()


def build_semantic_entropy_gate(model: EntailmentModel | None = None) -> SemanticEntropyGate:
    return SemanticEntropyGate(
        model=model if model is not None else build_entailment_model(),
        n_samples=settings.semantic_entropy_samples,
        entropy_threshold=settings.semantic_entropy_threshold,
        entailment_threshold=settings.semantic_entailment_threshold,
    )
