"""Exercises SqlAlchemyStatuteRepository for real against SQLite (via
aiosqlite) — there's no Postgres available to test against in this
environment. tests/integration/test_postgres_repository.py runs the same
repository against a real Postgres, but only under CI's `postgres` service
container.

A SQLite-backed SQLAlchemy async engine needs a real file (not `:memory:`)
for a fresh connection-per-session to see the same database — `:memory:`
gives each connection its own separate database unless you also configure
a StaticPool, which a temp file sidesteps entirely.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from legal_engine.core.models import GeoBoundary, JurisdictionTier, SourceType, StatuteDocument
from legal_engine.persistence.sql_repository import SqlAlchemyStatuteRepository

pytestmark = pytest.mark.asyncio


def _statute(citation: str = "Sec. 1", **overrides) -> StatuteDocument:
    defaults = {
        "source_type": SourceType.MUNICIPAL_CODE,
        "jurisdiction_tier": JurisdictionTier.MUNICIPAL,
        "citation": citation,
        "title": "Test Ordinance",
        "text": "No person shall...",
    }
    defaults.update(overrides)
    return StatuteDocument(**defaults)


@pytest.fixture
async def repo(tmp_path):
    dsn = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    repository = SqlAlchemyStatuteRepository(dsn)
    await repository.create_schema()
    yield repository
    await repository.close()


class TestSqlAlchemyStatuteRepository:
    async def test_add_and_get_roundtrip(self, repo):
        statute = _statute()
        await repo.add(statute)

        fetched = await repo.get(statute.id)
        assert fetched.id == statute.id
        assert fetched.citation == statute.citation
        assert fetched.title == statute.title
        assert fetched.text == statute.text
        assert fetched.source_type == statute.source_type
        assert fetched.jurisdiction_tier == statute.jurisdiction_tier

    async def test_roundtrip_preserves_geo_boundary(self, repo):
        statute = _statute(
            geo_boundary=GeoBoundary(lat_min=34.0, lat_max=34.1, lon_min=-118.3, lon_max=-118.2)
        )
        await repo.add(statute)

        fetched = await repo.get(statute.id)
        assert fetched.geo_boundary is not None
        assert fetched.geo_boundary.lat_min == 34.0
        assert fetched.geo_boundary.lon_max == -118.2

    async def test_roundtrip_without_geo_boundary_stays_none(self, repo):
        statute = _statute()
        await repo.add(statute)
        fetched = await repo.get(statute.id)
        assert fetched.geo_boundary is None

    async def test_applies_to_round_trips(self, repo):
        statute = _statute(applies_to=["entity-a", "entity-b"])
        await repo.add(statute)
        fetched = await repo.get(statute.id)
        assert fetched.applies_to == ["entity-a", "entity-b"]

    async def test_applies_to_defaults_to_empty_list(self, repo):
        statute = _statute()
        await repo.add(statute)
        fetched = await repo.get(statute.id)
        assert fetched.applies_to == []

    async def test_get_missing_returns_none(self, repo):
        assert await repo.get(uuid4()) is None

    async def test_list_by_citation(self, repo):
        a = _statute(citation="Sec. 1")
        b = _statute(citation="Sec. 1")
        other = _statute(citation="Sec. 2")
        await repo.add(a)
        await repo.add(b)
        await repo.add(other)

        results = await repo.list_by_citation("Sec. 1")
        assert {s.id for s in results} == {a.id, b.id}

    async def test_all_returns_every_statute(self, repo):
        statutes = [_statute(citation=f"Sec. {i}") for i in range(3)]
        for s in statutes:
            await repo.add(s)
        assert {s.id for s in await repo.all()} == {s.id for s in statutes}

    async def test_add_upserts_existing_id(self, repo):
        statute = _statute(text="original")
        await repo.add(statute)
        await repo.add(statute.model_copy(update={"text": "amended"}))

        fetched = await repo.get(statute.id)
        assert fetched.text == "amended"
        assert len(await repo.all()) == 1

    async def test_data_persists_across_separate_repository_instances(self, tmp_path):
        """Proves this is actually durable storage, not just an in-process
        cache: a brand new repository instance pointed at the same file
        sees data written by a previous one."""
        dsn = f"sqlite+aiosqlite:///{tmp_path}/durable.db"

        first = SqlAlchemyStatuteRepository(dsn)
        await first.create_schema()
        statute = _statute()
        await first.add(statute)
        await first.close()

        second = SqlAlchemyStatuteRepository(dsn)
        fetched = await second.get(statute.id)
        assert fetched is not None
        assert fetched.citation == statute.citation
        await second.close()
