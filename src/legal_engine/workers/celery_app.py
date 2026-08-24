"""Celery app configuration & broker setup.

Uses Redis as both broker and result backend, matching
docker/docker-compose.yml. Connecting to either requires a live Redis
instance, which this dev/test environment doesn't have — but task *logic*
in tasks.py is still fully testable without one: Celery task objects remain
plain callables, and ``task.apply(...)`` runs a task synchronously in-
process without touching the broker at all. Only ``.delay()`` /
``.apply_async()`` (real, distributed dispatch) need Redis actually
running.
"""

from __future__ import annotations

from celery import Celery

from legal_engine.core.config import settings

app = Celery(
    "legal_engine",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["legal_engine.workers.tasks"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)
