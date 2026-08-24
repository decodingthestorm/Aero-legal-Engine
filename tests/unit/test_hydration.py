import pytest

from legal_engine.core.models import JurisdictionTier, SourceType, StatuteDocument
from legal_engine.knowledge_graph.embeddings import HashingEmbedder
from legal_engine.knowledge_graph.graph_service import NetworkXGraphService
from legal_engine.knowledge_graph.vector_service import InMemoryVectorIndex
from legal_engine.persistence.hydration import hydrate_indexes
from legal_engine.persistence.repository import InMemoryStatuteRepository

pytestmark = pytest.mark.asyncio


def _statute(citation: str, applies_to: list[str]) -> StatuteDocument:
    return StatuteDocument(
        source_type=SourceType.MUNICIPAL_CODE,
        jurisdiction_tier=JurisdictionTier.MUNICIPAL,
        citation=citation,
        title=citation,
        text=f"text for {citation}",
        applies_to=applies_to,
    )


class TestHydrateIndexes:
    async def test_empty_repository_is_a_noop(self):
        repo = InMemoryStatuteRepository()
        graph = NetworkXGraphService()
        vector = InMemoryVectorIndex()
        embedder = HashingEmbedder()

        count = await hydrate_indexes(repo, graph, vector, embedder)

        assert count == 0
        assert graph.all_statutes() == []
        assert len(vector) == 0

    async def test_rebuilds_graph_edges_from_persisted_applies_to(self):
        repo = InMemoryStatuteRepository()
        statute = _statute("Sec. 1", applies_to=["entity-a", "entity-b"])
        await repo.add(statute)

        graph = NetworkXGraphService()
        vector = InMemoryVectorIndex()
        embedder = HashingEmbedder()

        count = await hydrate_indexes(repo, graph, vector, embedder)

        assert count == 1
        assert [s.citation for s in graph.statutes_for_entity("entity-a")] == ["Sec. 1"]
        assert [s.citation for s in graph.statutes_for_entity("entity-b")] == ["Sec. 1"]

    async def test_rebuilds_vector_index_entries(self):
        repo = InMemoryStatuteRepository()
        statute = _statute("Sec. 1", applies_to=[])
        await repo.add(statute)

        graph = NetworkXGraphService()
        vector = InMemoryVectorIndex()
        embedder = HashingEmbedder()

        await hydrate_indexes(repo, graph, vector, embedder)

        assert len(vector) == 1
        [match] = vector.search(embedder.embed(statute.text), top_k=1)
        assert match.id == statute.id
        assert match.metadata["citation"] == "Sec. 1"

    async def test_rehydrates_every_persisted_statute(self):
        repo = InMemoryStatuteRepository()
        for i in range(5):
            await repo.add(_statute(f"Sec. {i}", applies_to=[f"entity-{i}"]))

        graph = NetworkXGraphService()
        vector = InMemoryVectorIndex()
        embedder = HashingEmbedder()

        count = await hydrate_indexes(repo, graph, vector, embedder)

        assert count == 5
        assert len(graph.all_statutes()) == 5
        assert len(vector) == 5
