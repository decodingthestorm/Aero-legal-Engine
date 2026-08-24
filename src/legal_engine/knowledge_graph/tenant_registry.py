"""Per-tenant GraphService/VectorIndex instances — the other half of data
isolation alongside persistence/repository.py's tenant-scoped
StatuteRepository.

Unlike StatuteRepository (a single shared instance filtering every query by
tenant_id — natural for a relational table or one big dict), GraphService
and VectorIndex are cheap to construct (``NetworkXGraphService()`` wraps a
fresh ``nx.DiGraph``; ``InMemoryVectorIndex()`` wraps two empty dicts), so
instead of threading tenant_id through every method of both Protocols, each
tenant gets its own genuinely separate instance, lazily created on first
use and cached here. This is less invasive (GraphService/VectorIndex's
existing interfaces don't change at all) and gives a stronger isolation
guarantee than a shared-instance-plus-filter would: there's no shared
in-memory structure a bug in a filter clause could ever leak across, because
there's no shared structure at all.

Embedder is intentionally *not* tenant-scoped here — HashingEmbedder/
SentenceTransformerEmbedder are pure functions of input text with no
stored state, so there's nothing to isolate; every tenant safely shares one.

For the Neo4j/Qdrant backends (untested in this environment — see
knowledge_graph/factory.py), the same per-tenant-instance pattern still
applies structurally (one Neo4jGraphService/QdrantVectorIndex per tenant
via this registry), though a real deployment might instead prefer a single
shared Neo4j/Qdrant deployment with tenant_id as a node property / payload
filter, for operational reasons (connection pool limits, index count) this
registry doesn't have to weigh for the in-memory defaults it's actually
tested against.
"""

from __future__ import annotations

from legal_engine.knowledge_graph.factory import build_graph_service, build_vector_index
from legal_engine.knowledge_graph.graph_service import GraphService
from legal_engine.knowledge_graph.vector_service import VectorIndex


class TenantIndexRegistry:
    def __init__(self) -> None:
        self._graphs: dict[str, GraphService] = {}
        self._vectors: dict[str, VectorIndex] = {}

    def graph_for(self, tenant_id: str) -> GraphService:
        if tenant_id not in self._graphs:
            self._graphs[tenant_id] = build_graph_service()
        return self._graphs[tenant_id]

    def vector_for(self, tenant_id: str) -> VectorIndex:
        if tenant_id not in self._vectors:
            self._vectors[tenant_id] = build_vector_index()
        return self._vectors[tenant_id]

    def known_tenant_ids(self) -> list[str]:
        """Tenants with at least one lazily-created index so far — not the
        full set of tenants with data (a tenant with statutes but no index
        touched yet wouldn't appear); persistence/hydration.py uses
        StatuteRepository.list_tenant_ids() instead, which is authoritative."""
        return sorted(set(self._graphs) | set(self._vectors))
