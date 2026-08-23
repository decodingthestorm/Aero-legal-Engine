import httpx
import pytest

from legal_engine.core.models import SourceType
from legal_engine.ingestion.crawler_manager import IngestionJob, run_ingestion_jobs
from legal_engine.ingestion.rate_limiter import PoliteFetcher

pytestmark = pytest.mark.asyncio

_MUNICIPAL_HTML = """
<article class="ordinance" data-citation="Sec. 1" data-title="ADUs">
  <div class="ordinance-text">No person shall build without a permit.</div>
</article>
"""

_FEDERAL_XML = """
<FEDREG>
  <DOCUMENT citation="40 CFR 122.21" title="Permits"><TEXT>Apply for a permit.</TEXT></DOCUMENT>
</FEDREG>
"""


class TestRunIngestionJobs:
    async def test_dispatches_to_the_right_parser_per_job(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "municipal" in str(request.url):
                return httpx.Response(200, text=_MUNICIPAL_HTML)
            if "federal" in str(request.url):
                return httpx.Response(200, text=_FEDERAL_XML)
            raise AssertionError(f"unexpected URL {request.url}")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        fetcher = PoliteFetcher(client=client, min_delay_seconds=0, respect_robots_txt=False)

        jobs = [
            IngestionJob(url="https://example.gov/municipal", source_type=SourceType.MUNICIPAL_CODE),
            IngestionJob(url="https://example.gov/federal", source_type=SourceType.FEDERAL_CODE),
        ]
        statutes = await run_ingestion_jobs(jobs, fetcher)

        assert {s.citation for s in statutes} == {"Sec. 1", "40 CFR 122.21"}
        assert {s.source_type for s in statutes} == {SourceType.MUNICIPAL_CODE, SourceType.FEDERAL_CODE}
        await fetcher.aclose()

    async def test_unregistered_source_type_raises(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
        fetcher = PoliteFetcher(client=client, min_delay_seconds=0, respect_robots_txt=False)

        jobs = [IngestionJob(url="https://example.gov/x", source_type=SourceType.INTERNATIONAL_TREATY)]
        with pytest.raises(ValueError, match="No parser registered"):
            await run_ingestion_jobs(jobs, fetcher)
        await fetcher.aclose()

    async def test_http_error_propagates(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        fetcher = PoliteFetcher(client=client, min_delay_seconds=0, respect_robots_txt=False, max_retries=0)

        jobs = [IngestionJob(url="https://example.gov/x", source_type=SourceType.MUNICIPAL_CODE)]
        with pytest.raises(httpx.HTTPStatusError):
            await run_ingestion_jobs(jobs, fetcher)
        await fetcher.aclose()
