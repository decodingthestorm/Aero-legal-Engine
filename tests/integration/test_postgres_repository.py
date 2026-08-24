"""Runs SqlAlchemyStatuteRepository against a real Postgres.

tests/unit/test_sql_repository.py already exercises the same repository
code thoroughly against SQLite, since there's no Postgres available in the
environment this was developed in. That's a real, honest substitute for
most of the behavior, but it can't catch everything a genuine driver
(asyncpg) and a genuine Postgres server might do differently — UUID column
type mapping in particular is exactly the kind of thing that's silently
fine on SQLite and needs a real Postgres to actually prove.

Skipped unless LEGAL_ENGINE_TEST_POSTGRES_DSN is set. CI's `postgres` job
(.github/workflows/ci.yml) sets it against a genuine `postgres` service
container, so this suite does run for real there — just never locally in
this environment.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from legal_engine.core.models import GeoBoundary, JurisdictionTier, SourceType, StatuteDocument

_DSN = os.environ.get("LEGAL_ENGINE_TEST_POSTGRES_DSN")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        _DSN is None,
        reason="LEGAL_ENGINE_TEST_POSTGRES_DSN not set - no Postgres available to test against",
    ),
]


def _statute(**overrides) -> StatuteDocument:
    defaults = {
        "source_type": SourceType.MUNICIPAL_CODE,
        "jurisdiction_tier": JurisdictionTier.MUNICIPAL,
        "citation": f"Sec. PG-{uuid4()}",
        "title": "Postgres Integration Test",
        "text": "text",
    }
    defaults.update(overrides)
    return StatuteDocument(**defaults)


@pytest.fixture
async def repo():
    from legal_engine.persistence.sql_repository import SqlAlchemyStatuteRepository

    repository = SqlAlchemyStatuteRepository(_DSN)
    await repository.create_schema()
    yield repository
    await repository.close()


async def test_add_and_get_roundtrip_against_real_postgres(repo):
    statute = _statute()
    await repo.add(statute)

    fetched = await repo.get(statute.id)
    assert fetched.id == statute.id
    assert fetched.citation == statute.citation
    assert fetched.jurisdiction_tier == statute.jurisdiction_tier


async def test_geo_boundary_roundtrip_against_real_postgres(repo):
    statute = _statute(
        geo_boundary=GeoBoundary(lat_min=1.0, lat_max=2.0, lon_min=3.0, lon_max=4.0)
    )
    await repo.add(statute)

    fetched = await repo.get(statute.id)
    assert fetched.geo_boundary == statute.geo_boundary


async def test_list_by_citation_against_real_postgres(repo):
    citation = f"Sec. PG-Shared-{uuid4()}"
    a = _statute(citation=citation)
    b = _statute(citation=citation)
    await repo.add(a)
    await repo.add(b)

    results = await repo.list_by_citation(citation)
    assert {s.id for s in results} == {a.id, b.id}
