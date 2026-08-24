"""Text embedders producing 384-dimensional dense vectors for statute text.

``Embedder`` is a Protocol so vector_service.py and the ingestion pipeline
don't care which implementation backs it:

- ``HashingEmbedder``: deterministic, dependency-free feature-hashing bag-of-
  words embedding. Not semantically rich, but exact, offline, and instant —
  used by default and by the whole test suite.
- ``SentenceTransformerEmbedder``: wraps the real all-MiniLM-L6-v2 model via
  `sentence-transformers`. That package (plus its torch dependency) is a
  multi-hundred-MB install and the model weights are a further ~90MB
  download, so it's imported lazily in __init__ rather than at module load
  time, and it is not exercised by the test suite in this environment. This
  is the one to wire up for production semantic search quality.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, cast

from legal_engine.core.config import settings

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class Embedder(Protocol):
    dimension: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Deterministic bag-of-words embedding via feature hashing.

    Each token is hashed into one of `dimension` buckets (sign-hashed, so
    collisions partially cancel rather than only accumulate), and the
    resulting vector is L2-normalized so cosine similarity behaves sanely.
    """

    def __init__(self, dimension: int = settings.embedding_dim) -> None:
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]


class SentenceTransformerEmbedder:
    """Wraps sentence-transformers' all-MiniLM-L6-v2. Requires the optional
    `sentence-transformers` dependency; not used by the test suite here."""

    def __init__(self, model_name: str = settings.embedding_model) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            # Not just ImportError: sentence-transformers pulls in torch (and
            # transitively scipy/sklearn), whose native extensions can fail
            # to load for reasons that surface as OSError or a torch/scipy-
            # internal ImportError rather than "no module named X" — e.g. a
            # Windows Application Control policy blocking a DLL, or a CUDA/
            # driver mismatch. Whatever the underlying cause, the actionable
            # message is the same, so it's normalized to one ImportError here.
            raise ImportError(
                "SentenceTransformerEmbedder requires a working sentence-transformers "
                f"install: pip install sentence-transformers (underlying error: "
                f"{exc.__class__.__name__}: {exc})"
            ) from exc
        self._model = SentenceTransformer(model_name)
        self.dimension = self._model.get_sentence_embedding_dimension()

    def embed(self, text: str) -> list[float]:
        # .tolist() is Any here: numpy's stubs are skipped in the mypy
        # config (see pyproject.toml) because they need a newer target
        # than requires-python promises.
        return cast(list[float], self._model.encode(text, normalize_embeddings=True).tolist())
