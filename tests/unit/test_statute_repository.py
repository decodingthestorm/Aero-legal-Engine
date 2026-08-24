import pytest

from legal_engine.core.models import JurisdictionTier, SourceType, StatuteDocument
from legal_engine.persistence.repository import InMemoryStatuteRepository

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


class TestInMemoryStatuteRepository:
    async def test_add_and_get_roundtrip(self):
        repo = InMemoryStatuteRepository()
        statute = _statute()
        await repo.add(statute)
        assert await repo.get(statute.id) == statute

    async def test_get_missing_returns_none(self):
        repo = InMemoryStatuteRepository()
        from uuid import uuid4

        assert await repo.get(uuid4()) is None

    async def test_list_by_citation(self):
        repo = InMemoryStatuteRepository()
        a = _statute(citation="Sec. 1")
        b = _statute(citation="Sec. 1")
        other = _statute(citation="Sec. 2")
        await repo.add(a)
        await repo.add(b)
        await repo.add(other)

        results = await repo.list_by_citation("Sec. 1")
        assert {s.id for s in results} == {a.id, b.id}

    async def test_all_returns_every_statute(self):
        repo = InMemoryStatuteRepository()
        statutes = [_statute(citation=f"Sec. {i}") for i in range(3)]
        for s in statutes:
            await repo.add(s)
        assert {s.id for s in await repo.all()} == {s.id for s in statutes}

    async def test_add_overwrites_existing_id(self):
        repo = InMemoryStatuteRepository()
        statute = _statute(text="original")
        await repo.add(statute)
        updated = statute.model_copy(update={"text": "amended"})
        await repo.add(updated)
        assert (await repo.get(statute.id)).text == "amended"
        assert len(await repo.all()) == 1

    async def test_create_schema_and_close_are_safe_noops(self):
        repo = InMemoryStatuteRepository()
        await repo.create_schema()
        await repo.close()

    async def test_applies_to_round_trips(self):
        repo = InMemoryStatuteRepository()
        statute = _statute(applies_to=["entity-a", "entity-b"])
        await repo.add(statute)
        assert (await repo.get(statute.id)).applies_to == ["entity-a", "entity-b"]

    async def test_applies_to_defaults_to_empty_list(self):
        repo = InMemoryStatuteRepository()
        statute = _statute()
        await repo.add(statute)
        assert (await repo.get(statute.id)).applies_to == []
