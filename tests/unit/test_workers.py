"""Tests Celery task logic via .apply(...).get() — runs the task function
in-process, synchronously, with no broker/Redis involved (see
celery_app.py's and tasks.py's docstrings for why that's sufficient)."""

import httpx

from legal_engine.ingestion.rate_limiter import PoliteFetcher
from legal_engine.knowledge_graph.vector_service import InMemoryVectorIndex
from legal_engine.workers.tasks import crawl_and_parse, index_statute_embedding

_MUNICIPAL_HTML = """
<article class="ordinance" data-citation="Sec. 1" data-title="ADUs">
  <div class="ordinance-text">No person shall build without a permit.</div>
</article>
"""


class TestCrawlAndParse:
    def test_crawls_and_parses_via_injected_fetcher(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_MUNICIPAL_HTML)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        fetcher = PoliteFetcher(client=client, min_delay_seconds=0, respect_robots_txt=False)

        result = crawl_and_parse.apply(
            args=("https://example.gov/code", "municipal_code"), kwargs={"_fetcher": fetcher}
        ).get()

        assert len(result) == 1
        assert result[0]["citation"] == "Sec. 1"
        assert result[0]["source_type"] == "municipal_code"

    def test_task_is_named_for_broker_dispatch(self):
        assert crawl_and_parse.name == "legal_engine.crawl_and_parse"


class TestIndexStatuteEmbedding:
    def test_embeds_and_upserts_statute(self):
        from legal_engine.core.models import JurisdictionTier, SourceType, StatuteDocument

        statute = StatuteDocument(
            source_type=SourceType.MUNICIPAL_CODE,
            jurisdiction_tier=JurisdictionTier.MUNICIPAL,
            citation="Sec. 1",
            title="ADUs",
            text="No person shall build without a permit.",
        )

        result = index_statute_embedding.apply(args=(statute.model_dump(mode="json"),)).get()

        assert result["id"] == str(statute.id)
        assert result["dimension"] > 0
        assert result["index_size"] >= 1

    def test_task_is_named_for_broker_dispatch(self):
        assert index_statute_embedding.name == "legal_engine.index_statute_embedding"


def test_module_level_vector_index_is_a_real_in_memory_index():
    from legal_engine.workers import tasks

    assert isinstance(tasks._vector_index, InMemoryVectorIndex)
