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

from datetime import datetime
from uuid import uuid4

import pytest

from legal_engine.core.models import GeoBoundary, JurisdictionTier, SourceType, StatuteDocument
from legal_engine.persistence.sql_repository import SqlAlchemyStatuteRepository

pytestmark = pytest.mark.asyncio

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


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
        await repo.add(statute, TENANT_A)

        fetched = await repo.get(statute.id, TENANT_A)
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
        await repo.add(statute, TENANT_A)

        fetched = await repo.get(statute.id, TENANT_A)
        assert fetched.geo_boundary is not None
        assert fetched.geo_boundary.lat_min == 34.0
        assert fetched.geo_boundary.lon_max == -118.2

    async def test_roundtrip_without_geo_boundary_stays_none(self, repo):
        statute = _statute()
        await repo.add(statute, TENANT_A)
        fetched = await repo.get(statute.id, TENANT_A)
        assert fetched.geo_boundary is None

    async def test_ingested_at_comes_back_utc_aware(self, repo):
        """Same round-trip loss _as_utc fixes for UserAccount.created_at:
        neither SQLite nor Postgres preserves the offset on a plain
        datetime column, so a value written as UTC-aware came back naive.
        Nothing asserted on ingested_at before this."""
        statute = _statute()
        await repo.add(statute, TENANT_A)
        fetched = await repo.get(statute.id, TENANT_A)
        assert fetched.ingested_at.tzinfo is not None
        assert fetched.ingested_at == statute.ingested_at

    async def test_naive_effective_date_is_left_naive(self, repo):
        """_as_utc deliberately does *not* touch effective_date: it comes
        from a parsed source document, so whether it carries a timezone is
        a fact about the document. Stamping UTC on it would invent
        information the source never provided."""
        # DTZ001 (no tzinfo) is the entire point of this test — a source
        # document that gave a date with no timezone must stay that way.
        naive = datetime(2024, 1, 1, 12, 0, 0)  # noqa: DTZ001
        statute = _statute(effective_date=naive)
        await repo.add(statute, TENANT_A)
        fetched = await repo.get(statute.id, TENANT_A)
        assert fetched.effective_date == naive
        assert fetched.effective_date.tzinfo is None

    async def test_applies_to_round_trips(self, repo):
        statute = _statute(applies_to=["entity-a", "entity-b"])
        await repo.add(statute, TENANT_A)
        fetched = await repo.get(statute.id, TENANT_A)
        assert fetched.applies_to == ["entity-a", "entity-b"]

    async def test_applies_to_defaults_to_empty_list(self, repo):
        statute = _statute()
        await repo.add(statute, TENANT_A)
        fetched = await repo.get(statute.id, TENANT_A)
        assert fetched.applies_to == []

    async def test_get_missing_returns_none(self, repo):
        assert await repo.get(uuid4(), TENANT_A) is None

    async def test_list_by_citation(self, repo):
        a = _statute(citation="Sec. 1")
        b = _statute(citation="Sec. 1")
        other = _statute(citation="Sec. 2")
        await repo.add(a, TENANT_A)
        await repo.add(b, TENANT_A)
        await repo.add(other, TENANT_A)

        results = await repo.list_by_citation("Sec. 1", TENANT_A)
        assert {s.id for s in results} == {a.id, b.id}

    async def test_all_returns_every_statute(self, repo):
        statutes = [_statute(citation=f"Sec. {i}") for i in range(3)]
        for s in statutes:
            await repo.add(s, TENANT_A)
        assert {s.id for s in await repo.all(TENANT_A)} == {s.id for s in statutes}

    async def test_add_upserts_existing_id(self, repo):
        statute = _statute(text="original")
        await repo.add(statute, TENANT_A)
        await repo.add(statute.model_copy(update={"text": "amended"}), TENANT_A)

        fetched = await repo.get(statute.id, TENANT_A)
        assert fetched.text == "amended"
        assert len(await repo.all(TENANT_A)) == 1

    async def test_data_persists_across_separate_repository_instances(self, tmp_path):
        """Proves this is actually durable storage, not just an in-process
        cache: a brand new repository instance pointed at the same file
        sees data written by a previous one."""
        dsn = f"sqlite+aiosqlite:///{tmp_path}/durable.db"

        first = SqlAlchemyStatuteRepository(dsn)
        await first.create_schema()
        statute = _statute()
        await first.add(statute, TENANT_A)
        await first.close()

        second = SqlAlchemyStatuteRepository(dsn)
        fetched = await second.get(statute.id, TENANT_A)
        assert fetched is not None
        assert fetched.citation == statute.citation
        await second.close()


class TestTenantIsolation:
    async def test_get_does_not_leak_across_tenants(self, repo):
        statute = _statute()
        await repo.add(statute, TENANT_A)

        assert await repo.get(statute.id, TENANT_B) is None
        assert await repo.get(statute.id, TENANT_A) is not None

    async def test_list_by_citation_is_scoped_per_tenant(self, repo):
        a = _statute(citation="Shared Citation")
        b = _statute(citation="Shared Citation")
        await repo.add(a, TENANT_A)
        await repo.add(b, TENANT_B)

        assert [s.id for s in await repo.list_by_citation("Shared Citation", TENANT_A)] == [a.id]
        assert [s.id for s in await repo.list_by_citation("Shared Citation", TENANT_B)] == [b.id]

    async def test_all_is_scoped_per_tenant(self, repo):
        a = _statute(citation="Sec. A")
        b = _statute(citation="Sec. B")
        await repo.add(a, TENANT_A)
        await repo.add(b, TENANT_B)

        assert {s.id for s in await repo.all(TENANT_A)} == {a.id}
        assert {s.id for s in await repo.all(TENANT_B)} == {b.id}

    async def test_same_id_can_exist_independently_under_two_tenants(self, repo):
        statute = _statute()
        a_version = statute.model_copy(update={"text": "tenant a's text"})
        b_version = statute.model_copy(update={"text": "tenant b's text"})
        await repo.add(a_version, TENANT_A)
        await repo.add(b_version, TENANT_B)

        assert (await repo.get(statute.id, TENANT_A)).text == "tenant a's text"
        assert (await repo.get(statute.id, TENANT_B)).text == "tenant b's text"

    async def test_list_tenant_ids_returns_every_distinct_tenant(self, repo):
        await repo.add(_statute(citation="Sec. A"), TENANT_A)
        await repo.add(_statute(citation="Sec. B"), TENANT_B)

        assert await repo.list_tenant_ids() == sorted([TENANT_A, TENANT_B])

    async def test_list_tenant_ids_empty_when_no_data(self, repo):
        assert await repo.list_tenant_ids() == []
