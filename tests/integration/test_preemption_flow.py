"""End-to-end: embed statute text, use vector similarity to surface a
candidate conflict, tie the statutes to a shared graph entity, then resolve
which one governs under Article VI Supremacy Clause ordering.

This exercises embeddings.py -> vector_service.py -> graph_service.py ->
preemption.py together, which is the seam Phase 2 was actually meant to
build: none of these modules is interesting used in isolation.
"""

from __future__ import annotations

from legal_engine.core.models import JurisdictionTier, SourceType, StatuteDocument
from legal_engine.knowledge_graph.embeddings import HashingEmbedder
from legal_engine.knowledge_graph.graph_service import NetworkXGraphService
from legal_engine.knowledge_graph.preemption import resolve_all, resolve_preemption_for_entity
from legal_engine.knowledge_graph.vector_service import InMemoryVectorIndex


def _statute(citation: str, tier: JurisdictionTier, text: str) -> StatuteDocument:
    return StatuteDocument(
        source_type=SourceType.MUNICIPAL_CODE if tier == JurisdictionTier.MUNICIPAL else SourceType.STATE_STATUTE,
        jurisdiction_tier=tier,
        citation=citation,
        title=citation,
        text=text,
    )


class TestPreemptionFlow:
    def test_vector_similarity_surfaces_conflict_then_state_preempts_municipal(self):
        state_statute = _statute(
            "State Code 65.850",
            JurisdictionTier.STATE,
            "A short-term rental may operate in any residential zone provided the "
            "operator holds a valid state short-term rental permit.",
        )
        municipal_statute = _statute(
            "Muni Code 12.04.030",
            JurisdictionTier.MUNICIPAL,
            "No person shall operate a short-term rental in any residential zone "
            "within city limits under any circumstances.",
        )
        unrelated_statute = _statute(
            "Muni Code 8.02.010",
            JurisdictionTier.MUNICIPAL,
            "The annual municipal budget appropriation for fiscal year 2026 is "
            "hereby adopted as set forth in Schedule A.",
        )

        embedder = HashingEmbedder()
        index = InMemoryVectorIndex()
        for statute in (state_statute, municipal_statute, unrelated_statute):
            index.upsert(statute.id, embedder.embed(statute.text), {"citation": statute.citation})

        # The vector index is what tells us state_statute and municipal_statute
        # are about the same subject, not any explicit tagging at ingestion time.
        # (The 0.18 is_match threshold is calibrated for the real semantic
        # embedder, not this deterministic bag-of-words test double — so we
        # only assert relative ranking here, not the absolute distance.)
        query = embedder.embed(state_statute.text)
        matches = [m for m in index.search(query, top_k=3) if m.id != state_statute.id]
        top_match, other_match = matches[0], matches[1]
        assert top_match.id == municipal_statute.id
        assert other_match.id == unrelated_statute.id
        assert top_match.distance < other_match.distance

        graph = NetworkXGraphService()
        entity_id = "short_term_rental_regulation"
        graph.add_statute(state_statute, applies_to=[entity_id])
        graph.add_statute(municipal_statute, applies_to=[entity_id])
        graph.add_statute(unrelated_statute, applies_to=["municipal_budget_fy2026"])

        result = resolve_preemption_for_entity(graph, entity_id)

        assert result.governing.id == state_statute.id
        assert [s.id for s in result.preempted] == [municipal_statute.id]
        assert not result.requires_review
        assert graph.preemption_edges() == [(state_statute.id, municipal_statute.id)]

    def test_same_tier_conflict_requires_review_and_adds_no_edges(self):
        ordinance_a = _statute("Muni A", JurisdictionTier.MUNICIPAL, "text a")
        ordinance_b = _statute("Muni B", JurisdictionTier.MUNICIPAL, "text b")

        graph = NetworkXGraphService()
        entity_id = "conflicting_zoning_clause"
        graph.add_statute(ordinance_a, applies_to=[entity_id])
        graph.add_statute(ordinance_b, applies_to=[entity_id])

        result = resolve_preemption_for_entity(graph, entity_id)

        assert result.requires_review
        assert result.governing is None
        assert result.conflicting_tier == JurisdictionTier.MUNICIPAL
        assert graph.preemption_edges() == []

    def test_resolve_all_covers_every_entity_in_the_graph(self):
        graph = NetworkXGraphService()
        federal = _statute("Fed", JurisdictionTier.FEDERAL, "federal text")
        municipal = _statute("Muni", JurisdictionTier.MUNICIPAL, "municipal text")
        solo = _statute("Solo", JurisdictionTier.STATE, "solo text")

        graph.add_statute(federal, applies_to=["entity-1"])
        graph.add_statute(municipal, applies_to=["entity-1"])
        graph.add_statute(solo, applies_to=["entity-2"])

        results = {r.entity_id: r for r in resolve_all(graph)}

        assert results["entity-1"].governing.id == federal.id
        assert results["entity-2"].governing.id == solo.id
        assert results["entity-2"].preempted == []
