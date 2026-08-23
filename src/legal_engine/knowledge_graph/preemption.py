"""Article VI Supremacy Clause preemption resolution.

For every entity that two or more statutes apply to, the statute at the
numerically lowest ``JurisdictionTier`` (see core/models.py — treaty=0,
federal=1, state=2, county=3, municipal=4) governs, and the rest are
preempted. If more than one statute shares that minimal tier (e.g. two
municipal ordinances actually conflict), Article VI doesn't resolve that —
it's a same-tier conflict, not a hierarchy problem — so the result is
flagged ``requires_review`` instead of picking one arbitrarily.

This module only resolves *which statute wins* once a candidate conflict
set is known. Deciding whether statutes tied to the same entity actually
textually contradict each other is out of scope here — that's a job for
formal_logic/ (verify both statutes' compiled clauses are jointly UNSAT) or
for vector_service.py similarity search to surface as a candidate. Grouping
by "applies to the same entity" is a coarse, sound filter: statutes that
don't share a subject can't conflict, but sharing a subject doesn't by
itself prove they do.
"""

from __future__ import annotations

from dataclasses import dataclass

from legal_engine.core.models import JurisdictionTier, StatuteDocument
from legal_engine.knowledge_graph.graph_service import GraphService


@dataclass
class PreemptionResult:
    entity_id: str
    governing: StatuteDocument | None
    preempted: list[StatuteDocument]
    requires_review: bool
    conflicting_tier: JurisdictionTier | None = None


def resolve_preemption_for_entity(graph: GraphService, entity_id: str) -> PreemptionResult:
    statutes = graph.statutes_for_entity(entity_id)

    if not statutes:
        return PreemptionResult(entity_id=entity_id, governing=None, preempted=[], requires_review=False)

    if len(statutes) == 1:
        return PreemptionResult(
            entity_id=entity_id, governing=statutes[0], preempted=[], requires_review=False
        )

    min_tier = min(s.jurisdiction_tier for s in statutes)
    governing_candidates = [s for s in statutes if s.jurisdiction_tier == min_tier]

    if len(governing_candidates) > 1:
        return PreemptionResult(
            entity_id=entity_id,
            governing=None,
            preempted=[],
            requires_review=True,
            conflicting_tier=min_tier,
        )

    governing = governing_candidates[0]
    preempted = [s for s in statutes if s.id != governing.id]
    for subordinate in preempted:
        graph.add_preemption_edge(governing.id, subordinate.id)

    return PreemptionResult(
        entity_id=entity_id, governing=governing, preempted=preempted, requires_review=False
    )


def resolve_all(graph: GraphService) -> list[PreemptionResult]:
    return [resolve_preemption_for_entity(graph, entity_id) for entity_id in graph.all_entity_ids()]


def truncate_preempted_text(statute: StatuteDocument, reason: str = "preempted") -> StatuteDocument:
    """Return a copy of `statute` with its operative text truncated, marking
    it preempted so it doesn't reach formal_logic/ verification as if it
    were still live law. The original document is left untouched — this is
    a view for downstream consumers, not a mutation of ingested history."""
    return statute.model_copy(update={"text": f"[{reason.upper()}] {statute.citation} superseded."})
