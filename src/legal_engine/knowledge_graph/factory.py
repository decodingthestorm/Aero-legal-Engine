"""Settings-driven factory for the knowledge_graph backends.

Picks the in-memory default or the real Neo4j/Qdrant/sentence-transformers
implementation for each Protocol based on core.config.settings, so callers
(api/main.py's lifespan, workers/tasks.py, or a future CLI) don't need to
know which one they're getting — they just call the factory and get back
something satisfying GraphService/VectorIndex/Embedder either way.

Selecting a "real" backend without its install extra actually installed
(graph-neo4j / vector-qdrant / semantic) doesn't fail here — it fails
inside the concrete class's lazily-imported constructor, with a message
naming the exact `pip install` needed. That's deliberate: a clearer error
at the point of actual use beats a vague one here, and it means this
module never needs to know what any backend's install extra is called.
"""

from __future__ import annotations

from legal_engine.core.config import settings
from legal_engine.knowledge_graph.embeddings import (
    Embedder,
    HashingEmbedder,
    SentenceTransformerEmbedder,
)
from legal_engine.knowledge_graph.graph_service import (
    GraphService,
    Neo4jGraphService,
    NetworkXGraphService,
)
from legal_engine.knowledge_graph.vector_service import (
    InMemoryVectorIndex,
    QdrantVectorIndex,
    VectorIndex,
)


def build_graph_service() -> GraphService:
    if settings.graph_backend == "neo4j":
        return Neo4jGraphService(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    return NetworkXGraphService()


def build_vector_index() -> VectorIndex:
    if settings.vector_backend == "qdrant":
        return QdrantVectorIndex(collection_name=settings.qdrant_collection_name, url=settings.qdrant_url)
    return InMemoryVectorIndex()


def build_embedder() -> Embedder:
    if settings.embedding_backend == "sentence_transformers":
        return SentenceTransformerEmbedder(settings.embedding_model)
    return HashingEmbedder(settings.embedding_dim)
