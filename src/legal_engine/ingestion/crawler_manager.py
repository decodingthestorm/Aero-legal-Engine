"""Async ingestion dispatcher.

Fetches a batch of source URLs through PoliteFetcher (rate_limiter.py — it
already enforces robots.txt, per-host spacing, and bounded concurrency, so
no separate worker pool is layered on top here), dispatches each response
body to the parser matching its SourceType, and returns the resulting
StatuteDocuments.

Treaty ingestion isn't registered in ``_PARSERS``: parse_treaty_xml returns
``ParsedTreatyArticle`` (statute + language + choice-of-law), a different
shape than the plain ``list[StatuteDocument]`` the other parsers return, so
it's invoked directly by callers that need the extra fields rather than
forced into this uniform dispatch table.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from legal_engine.core.models import SourceType, StatuteDocument
from legal_engine.ingestion.parsers.federal import parse_federal_register_xml
from legal_engine.ingestion.parsers.municipal import parse_municipal_html
from legal_engine.ingestion.rate_limiter import PoliteFetcher

ParserFn = Callable[..., list[StatuteDocument]]

_PARSERS: dict[SourceType, ParserFn] = {
    SourceType.FEDERAL_CODE: parse_federal_register_xml,
    SourceType.MUNICIPAL_CODE: parse_municipal_html,
}


@dataclass
class IngestionJob:
    url: str
    source_type: SourceType


async def run_ingestion_jobs(
    jobs: list[IngestionJob], fetcher: PoliteFetcher
) -> list[StatuteDocument]:
    async def _run_one(job: IngestionJob) -> list[StatuteDocument]:
        parser = _PARSERS.get(job.source_type)
        if parser is None:
            raise ValueError(
                f"No parser registered in crawler_manager for source type {job.source_type}"
            )
        response = await fetcher.fetch(job.url)
        response.raise_for_status()
        return parser(response.text, source_url=job.url)

    batches = await asyncio.gather(*(_run_one(job) for job in jobs))
    return [statute for batch in batches for statute in batch]
