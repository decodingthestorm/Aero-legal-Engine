"""Tests knowledge_graph.factory's dispatch logic.

Selecting a "real" backend (neo4j/qdrant/sentence_transformers) without its
install extra actually installed isn't mocked around here — it's asserted
to raise ImportError with a helpful message. That's the actual contract:
the factory dispatches correctly, and the concrete class's lazy import is
what enforces "you need to pip install X to use this."
"""

import pytest

from legal_engine.core.config import settings
from legal_engine.knowledge_graph.embeddings import HashingEmbedder
from legal_engine.knowledge_graph.factory import (
    build_embedder,
    build_graph_service,
    build_vector_index,
)
from legal_engine.knowledge_graph.graph_service import NetworkXGraphService
from legal_engine.knowledge_graph.vector_service import InMemoryVectorIndex


class TestDefaultBackends:
    def test_default_graph_service_is_networkx(self):
        assert isinstance(build_graph_service(), NetworkXGraphService)

    def test_default_vector_index_is_in_memory(self):
        assert isinstance(build_vector_index(), InMemoryVectorIndex)

    def test_default_embedder_is_hashing(self):
        assert isinstance(build_embedder(), HashingEmbedder)


class TestBackendSwitchWithoutOptionalDependency:
    def test_neo4j_backend_fails_closed_with_install_hint(self, monkeypatch):
        monkeypatch.setattr(settings, "graph_backend", "neo4j")
        with pytest.raises(ImportError, match="pip install neo4j"):
            build_graph_service()

    def test_qdrant_backend_fails_closed_with_install_hint(self, monkeypatch):
        monkeypatch.setattr(settings, "vector_backend", "qdrant")
        with pytest.raises(ImportError, match="pip install qdrant-client"):
            build_vector_index()

    def test_sentence_transformers_backend_fails_closed_with_install_hint(self, monkeypatch):
        monkeypatch.setattr(settings, "embedding_backend", "sentence_transformers")
        with pytest.raises(ImportError, match="pip install sentence-transformers"):
            build_embedder()
