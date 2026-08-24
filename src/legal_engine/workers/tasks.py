"""Background tasks for crawling and vector indexing.

Two tasks, both callable directly via ``.apply(args=...).get()`` in tests
without a broker (see celery_app.py's docstring):

- ``crawl_and_parse``: runs the async ingestion pipeline (rate_limiter.py +
  crawler_manager.py) synchronously from Celery's sync task context via
  ``asyncio.run``, and returns parsed statutes as JSON-safe dicts.
- ``index_statute_embedding``: embeds a statute's text and upserts it into
  the vector index.

``index_statute_embedding`` uses module-level ``HashingEmbedder`` +
``InMemoryVectorIndex`` singletons — the same default, in-process
backends knowledge_graph/ uses elsewhere. A real deployment would swap
these for ``SentenceTransformerEmbedder`` and ``QdrantVectorIndex``
(both already implemented, lazily imported, in knowledge_graph/) via a
settings-driven factory; that wiring is left for whenever this actually
gets deployed against a live Qdrant instance, since there's nothing to
usefully test against here.

A WAL-append task is deliberately not included yet: doing that safely
needs a process-wide signing-key management story (where the Ed25519
private key comes from, how workers share one) that's a real design
decision, not something to default silently. Call
``legal_engine.core.wal.WriteAheadLog.append`` directly from whichever
component actually holds the key, until that's decided.
"""

from __future__ import annotations

import asyncio
from typing import Any

from legal_engine.core.models import SourceType, StatuteDocument
from legal_engine.ingestion.crawler_manager import IngestionJob, run_ingestion_jobs
from legal_engine.ingestion.rate_limiter import PoliteFetcher
from legal_engine.knowledge_graph.embeddings import HashingEmbedder
from legal_engine.knowledge_graph.vector_service import InMemoryVectorIndex
from legal_engine.workers.celery_app import app

_embedder = HashingEmbedder()
_vector_index = InMemoryVectorIndex()


@app.task(name="legal_engine.crawl_and_parse")
def crawl_and_parse(url: str, source_type: str, _fetcher: PoliteFetcher | None = None) -> list[dict[str, Any]]:
    """``_fetcher`` is a test seam, not part of the task's production contract:
    real dispatch via .delay()/.apply_async() never passes it (JSON-serialized
    args can't carry a live PoliteFetcher anyway), so it defaults to a real
    one. Tests call this via .apply(kwargs={"_fetcher": ...}) — which runs
    in-process without going through the broker or its serializer — to inject
    a PoliteFetcher wired to a mock transport instead of real network access.
    """

    async def _run() -> list[StatuteDocument]:
        fetcher = _fetcher if _fetcher is not None else PoliteFetcher()
        try:
            job = IngestionJob(url=url, source_type=SourceType(source_type))
            return await run_ingestion_jobs([job], fetcher)
        finally:
            if _fetcher is None:
                await fetcher.aclose()

    statutes = asyncio.run(_run())
    return [statute.model_dump(mode="json") for statute in statutes]


@app.task(name="legal_engine.index_statute_embedding")
def index_statute_embedding(statute_dict: dict[str, Any]) -> dict[str, Any]:
    statute = StatuteDocument.model_validate(statute_dict)
    vector = _embedder.embed(statute.text)
    _vector_index.upsert(statute.id, vector, {"citation": statute.citation, "title": statute.title})
    return {"id": str(statute.id), "dimension": len(vector), "index_size": len(_vector_index)}
