"""The durable, queryable system-of-record for ingested statutes.

Separate concern from knowledge_graph/: GraphService and VectorIndex are
*indexes* — a graph traversal structure and a similarity-search structure,
both rebuildable from the raw ingested statutes. StatuteRepository is where
those raw statutes actually live so they survive a process restart (when
backed by SqlAlchemyStatuteRepository — see sql_repository.py) instead of
existing only inside whatever in-memory index happened to be built from
them.

``InMemoryStatuteRepository`` lives here (no SQLAlchemy import, always
available) rather than alongside ``SqlAlchemyStatuteRepository`` in
sql_repository.py, because that module's ORM model class needs
SQLAlchemy's types at class-definition time, not just inside a
constructor — so it's a hard import at the top of that file. Splitting the
files means importing this module (to get the always-available in-memory
default) never requires SQLAlchemy to be installed.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from legal_engine.core.models import StatuteDocument


class StatuteRepository(Protocol):
    async def add(self, statute: StatuteDocument) -> None: ...

    async def get(self, statute_id: UUID) -> StatuteDocument | None: ...

    async def list_by_citation(self, citation: str) -> list[StatuteDocument]: ...

    async def all(self) -> list[StatuteDocument]: ...

    async def create_schema(self) -> None: ...

    async def close(self) -> None: ...


class InMemoryStatuteRepository:
    def __init__(self) -> None:
        self._statutes: dict[UUID, StatuteDocument] = {}

    async def add(self, statute: StatuteDocument) -> None:
        self._statutes[statute.id] = statute

    async def get(self, statute_id: UUID) -> StatuteDocument | None:
        return self._statutes.get(statute_id)

    async def list_by_citation(self, citation: str) -> list[StatuteDocument]:
        return [s for s in self._statutes.values() if s.citation == citation]

    async def all(self) -> list[StatuteDocument]:
        return list(self._statutes.values())

    async def create_schema(self) -> None:
        pass  # nothing to create for an in-memory dict

    async def close(self) -> None:
        pass  # nothing to release
