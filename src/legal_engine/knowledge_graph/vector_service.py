"""Dense vector index for semantic statute search.

``VectorIndex`` is a Protocol; ``InMemoryVectorIndex`` (brute-force cosine
similarity over numpy arrays) is what the test suite and local dev use.
``QdrantVectorIndex`` wraps a real Qdrant deployment for production —
requires the optional `qdrant-client` package and a running server, so its
import is deferred to __init__ and it isn't exercised by tests here.

Cosine *distance* (1 - cosine similarity) is the unit used throughout, to
match the spec's ``D_cosine <= 0.18`` match threshold
(settings.cosine_similarity_threshold): smaller distance = more similar,
0 = identical direction, 2 = opposite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import numpy as np

from legal_engine.core.config import settings


@dataclass
class VectorMatch:
    id: UUID
    distance: float
    metadata: dict[str, Any]

    @property
    def is_match(self) -> bool:
        return self.distance <= settings.cosine_similarity_threshold


class VectorIndex(Protocol):
    def upsert(self, id: UUID, vector: list[float], metadata: dict[str, Any]) -> None: ...

    def search(self, query_vector: list[float], top_k: int = 10) -> list[VectorMatch]: ...


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0.0:
        return 1.0  # undefined direction; treat as maximally dissimilar-but-not-opposite
    similarity = float(np.dot(a, b) / denom)
    similarity = max(-1.0, min(1.0, similarity))  # clamp float drift outside [-1, 1]
    return 1.0 - similarity


class InMemoryVectorIndex:
    """Brute-force cosine search over an in-process dict of vectors."""

    def __init__(self) -> None:
        self._vectors: dict[UUID, np.ndarray] = {}
        self._metadata: dict[UUID, dict[str, Any]] = {}

    def upsert(self, id: UUID, vector: list[float], metadata: dict[str, Any]) -> None:
        self._vectors[id] = np.array(vector, dtype=float)
        self._metadata[id] = metadata

    def search(self, query_vector: list[float], top_k: int = 10) -> list[VectorMatch]:
        query = np.array(query_vector, dtype=float)
        scored = [
            VectorMatch(id=vec_id, distance=cosine_distance(query, vec), metadata=self._metadata[vec_id])
            for vec_id, vec in self._vectors.items()
        ]
        scored.sort(key=lambda m: m.distance)
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._vectors)


class QdrantVectorIndex:
    """Qdrant-backed VectorIndex. Requires a running Qdrant instance and the
    `qdrant-client` package; not exercised by the test suite here."""

    def __init__(self, collection_name: str, url: str = settings.qdrant_url) -> None:
        try:
            from qdrant_client import QdrantClient
        except Exception as exc:
            raise ImportError(
                "QdrantVectorIndex requires the 'qdrant-client' package: pip install qdrant-client "
                f"(underlying error: {exc.__class__.__name__}: {exc})"
            ) from exc
        self._client = QdrantClient(url=url)
        self._collection_name = collection_name

    def upsert(self, id: UUID, vector: list[float], metadata: dict[str, Any]) -> None:
        from qdrant_client.models import PointStruct

        self._client.upsert(
            collection_name=self._collection_name,
            points=[PointStruct(id=str(id), vector=vector, payload=metadata)],
        )

    def search(self, query_vector: list[float], top_k: int = 10) -> list[VectorMatch]:
        results = self._client.search(
            collection_name=self._collection_name, query_vector=query_vector, limit=top_k
        )
        return [
            VectorMatch(id=UUID(r.id), distance=1.0 - r.score, metadata=r.payload or {})
            for r in results
        ]
