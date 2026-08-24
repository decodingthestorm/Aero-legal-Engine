"""Rebuilds each tenant's in-memory graph/vector indexes from the durable
statute repository at startup.

GraphService and VectorIndex are *indexes*, not the source of truth (see
repository.py's module docstring) — when they're backed by the in-memory
defaults, they start empty on every process restart regardless of whether
the underlying StatuteRepository is durable, and (since knowledge_graph/
tenant_registry.py) empty for every tenant on every startup, since
TenantIndexRegistry lazily builds a fresh instance per tenant on first
access rather than persisting them. graph_backend, vector_backend, and
statute_backend (core/config.py) are three independent settings — mix
statute_backend="sql" with the in-memory graph/vector defaults and, without
this, every durably-recorded statute would be invisible to preemption
resolution and semantic search after a restart until someone re-submitted
it through the API.

Iterates StatuteRepository.list_tenant_ids() — the authoritative source of
which tenants have any durable data — rather than
TenantIndexRegistry.known_tenant_ids(), since the registry is empty at
startup (nothing has lazily touched it yet).

Safe to call unconditionally on every startup: for the default in-memory
statute_backend, list_tenant_ids() is always empty on a fresh process
(nothing was ever durably recorded), so this is a no-op — no need to
branch on which backend is configured.
"""

from __future__ import annotations

from legal_engine.knowledge_graph.embeddings import Embedder
from legal_engine.knowledge_graph.tenant_registry import TenantIndexRegistry
from legal_engine.persistence.repository import StatuteRepository


async def hydrate_indexes(
    statute_repository: StatuteRepository,
    tenant_registry: TenantIndexRegistry,
    embedder: Embedder,
) -> int:
    """Returns the total number of statutes rehydrated, across all tenants."""
    total = 0
    for tenant_id in await statute_repository.list_tenant_ids():
        graph_service = tenant_registry.graph_for(tenant_id)
        vector_index = tenant_registry.vector_for(tenant_id)
        statutes = await statute_repository.all(tenant_id)
        for statute in statutes:
            graph_service.add_statute(statute, applies_to=statute.applies_to)
            vector_index.upsert(
                statute.id, embedder.embed(statute.text), {"citation": statute.citation}
            )
        total += len(statutes)
    return total
