import pytest

from legal_engine.core.models import JurisdictionTier, SourceType, StatuteDocument
from legal_engine.knowledge_graph.embeddings import HashingEmbedder
from legal_engine.knowledge_graph.tenant_registry import TenantIndexRegistry
from legal_engine.persistence.hydration import hydrate_indexes
from legal_engine.persistence.repository import InMemoryStatuteRepository

pytestmark = pytest.mark.asyncio

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


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
        registry = TenantIndexRegistry()
        embedder = HashingEmbedder()

        count = await hydrate_indexes(repo, registry, embedder)

        assert count == 0
        assert registry.known_tenant_ids() == []

    async def test_rebuilds_graph_edges_from_persisted_applies_to(self):
        repo = InMemoryStatuteRepository()
        statute = _statute("Sec. 1", applies_to=["entity-a", "entity-b"])
        await repo.add(statute, TENANT_A)

        registry = TenantIndexRegistry()
        embedder = HashingEmbedder()

        count = await hydrate_indexes(repo, registry, embedder)

        assert count == 1
        graph = registry.graph_for(TENANT_A)
        assert [s.citation for s in graph.statutes_for_entity("entity-a")] == ["Sec. 1"]
        assert [s.citation for s in graph.statutes_for_entity("entity-b")] == ["Sec. 1"]

    async def test_rebuilds_vector_index_entries(self):
        repo = InMemoryStatuteRepository()
        statute = _statute("Sec. 1", applies_to=[])
        await repo.add(statute, TENANT_A)

        registry = TenantIndexRegistry()
        embedder = HashingEmbedder()

        await hydrate_indexes(repo, registry, embedder)

        vector = registry.vector_for(TENANT_A)
        assert len(vector) == 1
        [match] = vector.search(embedder.embed(statute.text), top_k=1)
        assert match.id == statute.id
        assert match.metadata["citation"] == "Sec. 1"

    async def test_rehydrates_every_persisted_statute(self):
        repo = InMemoryStatuteRepository()
        for i in range(5):
            await repo.add(_statute(f"Sec. {i}", applies_to=[f"entity-{i}"]), TENANT_A)

        registry = TenantIndexRegistry()
        embedder = HashingEmbedder()

        count = await hydrate_indexes(repo, registry, embedder)

        assert count == 5
        graph = registry.graph_for(TENANT_A)
        vector = registry.vector_for(TENANT_A)
        assert len(graph.all_statutes()) == 5
        assert len(vector) == 5

    async def test_hydrates_each_tenant_into_its_own_isolated_indexes(self):
        repo = InMemoryStatuteRepository()
        await repo.add(_statute("Sec. A", applies_to=["entity-a"]), TENANT_A)
        await repo.add(_statute("Sec. B", applies_to=["entity-b"]), TENANT_B)

        registry = TenantIndexRegistry()
        embedder = HashingEmbedder()

        count = await hydrate_indexes(repo, registry, embedder)

        assert count == 2
        assert [s.citation for s in registry.graph_for(TENANT_A).all_statutes()] == ["Sec. A"]
        assert [s.citation for s in registry.graph_for(TENANT_B).all_statutes()] == ["Sec. B"]
        # Neither tenant's entity resolves against the other's graph.
        assert registry.graph_for(TENANT_A).statutes_for_entity("entity-b") == []
        assert registry.graph_for(TENANT_B).statutes_for_entity("entity-a") == []
