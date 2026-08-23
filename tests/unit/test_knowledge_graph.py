import numpy as np
import pytest

from legal_engine.core.models import JurisdictionTier, SourceType, StatuteDocument
from legal_engine.knowledge_graph.embeddings import HashingEmbedder
from legal_engine.knowledge_graph.graph_service import NetworkXGraphService
from legal_engine.knowledge_graph.vector_service import InMemoryVectorIndex, cosine_distance


def _statute(citation: str, tier: JurisdictionTier, text: str = "text") -> StatuteDocument:
    return StatuteDocument(
        source_type=SourceType.MUNICIPAL_CODE,
        jurisdiction_tier=tier,
        citation=citation,
        title=citation,
        text=text,
    )


class TestNetworkXGraphService:
    def test_add_and_get_statute(self):
        graph = NetworkXGraphService()
        statute = _statute("Sec. 1", JurisdictionTier.MUNICIPAL)
        graph.add_statute(statute, applies_to=["parcel-1"])
        assert graph.get_statute(statute.id) == statute

    def test_get_missing_statute_raises(self):
        graph = NetworkXGraphService()
        with pytest.raises(KeyError):
            graph.get_statute(_statute("x", JurisdictionTier.FEDERAL).id)

    def test_statutes_for_entity_groups_by_shared_entity(self):
        graph = NetworkXGraphService()
        federal = _statute("Fed. Sec. 1", JurisdictionTier.FEDERAL)
        municipal = _statute("Muni. Sec. 1", JurisdictionTier.MUNICIPAL)
        unrelated = _statute("Unrelated", JurisdictionTier.STATE)

        graph.add_statute(federal, applies_to=["parcel-1"])
        graph.add_statute(municipal, applies_to=["parcel-1"])
        graph.add_statute(unrelated, applies_to=["parcel-2"])

        statutes = graph.statutes_for_entity("parcel-1")
        assert {s.id for s in statutes} == {federal.id, municipal.id}

    def test_statutes_for_unknown_entity_returns_empty(self):
        graph = NetworkXGraphService()
        assert graph.statutes_for_entity("does-not-exist") == []

    def test_add_preemption_edge_requires_both_statutes_present(self):
        graph = NetworkXGraphService()
        federal = _statute("Fed", JurisdictionTier.FEDERAL)
        graph.add_statute(federal, applies_to=["parcel-1"])
        with pytest.raises(KeyError):
            graph.add_preemption_edge(federal.id, _statute("Other", JurisdictionTier.MUNICIPAL).id)

    def test_preemption_edges_roundtrip(self):
        graph = NetworkXGraphService()
        federal = _statute("Fed", JurisdictionTier.FEDERAL)
        municipal = _statute("Muni", JurisdictionTier.MUNICIPAL)
        graph.add_statute(federal, applies_to=["parcel-1"])
        graph.add_statute(municipal, applies_to=["parcel-1"])
        graph.add_preemption_edge(federal.id, municipal.id)
        assert graph.preemption_edges() == [(federal.id, municipal.id)]

    def test_all_entity_ids(self):
        graph = NetworkXGraphService()
        graph.add_statute(_statute("A", JurisdictionTier.FEDERAL), applies_to=["parcel-1", "parcel-2"])
        assert set(graph.all_entity_ids()) == {"parcel-1", "parcel-2"}


class TestHashingEmbedder:
    def test_dimension_matches_configured_value(self):
        embedder = HashingEmbedder(dimension=384)
        vector = embedder.embed("no person shall construct an accessory dwelling unit")
        assert len(vector) == 384

    def test_deterministic(self):
        embedder = HashingEmbedder(dimension=384)
        text = "zoning ordinance section 12.04.030"
        assert embedder.embed(text) == embedder.embed(text)

    def test_different_text_gives_different_vector(self):
        embedder = HashingEmbedder(dimension=384)
        assert embedder.embed("zoning ordinance") != embedder.embed("tax exemption clause")

    def test_similar_text_is_closer_than_dissimilar_text(self):
        embedder = HashingEmbedder(dimension=384)
        base = embedder.embed("no person shall operate a short term rental without a permit")
        similar = embedder.embed("no person shall operate a short term rental unit without a permit")
        different = embedder.embed("the annual budget appropriation for fiscal year 2026")

        base_np, similar_np, different_np = np.array(base), np.array(similar), np.array(different)
        assert cosine_distance(base_np, similar_np) < cosine_distance(base_np, different_np)

    def test_empty_text_returns_zero_vector(self):
        embedder = HashingEmbedder(dimension=16)
        assert embedder.embed("   ") == [0.0] * 16


class TestInMemoryVectorIndex:
    def test_search_returns_closest_first(self):
        index = InMemoryVectorIndex()
        id_a, id_b, id_c = _uuids(3)
        index.upsert(id_a, [1.0, 0.0], {"label": "a"})
        index.upsert(id_b, [0.0, 1.0], {"label": "b"})
        index.upsert(id_c, [0.9, 0.1], {"label": "c"})

        results = index.search([1.0, 0.0], top_k=3)
        assert [r.id for r in results] == [id_a, id_c, id_b]

    def test_identical_vector_has_zero_distance(self):
        index = InMemoryVectorIndex()
        (id_a,) = _uuids(1)
        index.upsert(id_a, [1.0, 2.0, 3.0], {})
        [result] = index.search([1.0, 2.0, 3.0], top_k=1)
        assert result.distance == pytest.approx(0.0, abs=1e-9)

    def test_opposite_vector_has_max_distance(self):
        index = InMemoryVectorIndex()
        (id_a,) = _uuids(1)
        index.upsert(id_a, [1.0, 0.0], {})
        [result] = index.search([-1.0, 0.0], top_k=1)
        assert result.distance == pytest.approx(2.0, abs=1e-9)

    def test_is_match_respects_threshold(self):
        from legal_engine.knowledge_graph.vector_service import VectorMatch

        close = VectorMatch(id=_uuids(1)[0], distance=0.1, metadata={})
        far = VectorMatch(id=_uuids(1)[0], distance=0.5, metadata={})
        assert close.is_match
        assert not far.is_match


def _uuids(n: int):
    from uuid import uuid4

    return [uuid4() for _ in range(n)]
