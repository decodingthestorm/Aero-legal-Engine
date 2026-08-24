"""Ingestion management endpoints.

Runs a crawl+parse job synchronously against the shared PoliteFetcher
(app.state.fetcher, see main.py's lifespan). This is the API's own
immediate-response path; workers/tasks.py's crawl_and_parse Celery task is
the separate background/async-dispatch path for larger batches — the two
don't share code because they have different failure-handling needs (an
API call should fail fast and return an error; a background job should
retry).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from legal_engine.api.dependencies import FetcherDep
from legal_engine.core.models import SourceType, StatuteDocument
from legal_engine.ingestion.crawler_manager import IngestionJob, run_ingestion_jobs

router = APIRouter()


class IngestJobRequest(BaseModel):
    url: str
    source_type: SourceType


@router.post("/jobs", response_model=list[StatuteDocument])
async def run_ingestion_job(request: IngestJobRequest, fetcher: FetcherDep) -> list[StatuteDocument]:
    job = IngestionJob(url=request.url, source_type=request.source_type)
    return await run_ingestion_jobs([job], fetcher)
