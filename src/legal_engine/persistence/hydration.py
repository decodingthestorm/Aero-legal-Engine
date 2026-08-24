"""Rebuilds the in-memory graph/vector indexes from the durable statute
repository at startup.

GraphService and VectorIndex are *indexes*, not the source of truth (see
repository.py's module docstring) — when they're backed by the in-memory
defaults, they start empty on every process restart regardless of whether
the underlying StatuteRepository is durable. graph_backend, vector_backend,
and statute_backend (core/config.py) are three independent settings — mix
statute_backend="sql" with the in-memory graph/vector defaults and, without
this, every durably-recorded statute would be invisible to preemption
resolution and semantic search after a restart until someone re-submitted
it through the API.

Safe to call unconditionally on every startup: for the default in-memory
statute_backend, StatuteRepository.all() is always empty on a fresh
process (nothing was ever durably recorded), so this is a no-op — no need
to branch on which backend is configured.
"""

from __future__ import annotations

from legal_engine.knowledge_graph.embeddings import Embedder
from legal_engine.knowledge_graph.graph_service import GraphService
from legal_engine.knowledge_graph.vector_service import VectorIndex
from legal_engine.persistence.repository import StatuteRepository


async def hydrate_indexes(
    statute_repository: StatuteRepository,
    graph_service: GraphService,
    vector_index: VectorIndex,
    embedder: Embedder,
) -> int:
    """Returns the number of statutes rehydrated."""
    statutes = await statute_repository.all()
    for statute in statutes:
        graph_service.add_statute(statute, applies_to=statute.applies_to)
        vector_index.upsert(
            statute.id, embedder.embed(statute.text), {"citation": statute.citation}
        )
    return len(statutes)
