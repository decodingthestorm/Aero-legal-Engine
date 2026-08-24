"""The durable, queryable system-of-record for ingested statutes.

Separate concern from knowledge_graph/: GraphService and VectorIndex are
*indexes* — a graph traversal structure and a similarity-search structure,
both rebuildable from the raw ingested statutes. StatuteRepository is where
those raw statutes actually live so they survive a process restart (when
backed by SqlAlchemyStatuteRepository — see sql_repository.py) instead of
existing only inside whatever in-memory index happened to be built from
them.

Every method takes ``tenant_id`` and scopes to it — this is the
multi-tenant data isolation boundary: a statute added under one tenant_id
is invisible to every other tenant_id, full stop. ``get``/
``list_by_citation``/``all`` never leak even the *existence* of another
tenant's data (a missing statute and one that exists under a different
tenant are indistinguishable to the caller — both come back as "not
found"), which is the property that actually matters for isolation, not
just "the data happens to be tagged."

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
    async def add(self, statute: StatuteDocument, tenant_id: str) -> None: ...

    async def get(self, statute_id: UUID, tenant_id: str) -> StatuteDocument | None: ...

    async def list_by_citation(self, citation: str, tenant_id: str) -> list[StatuteDocument]: ...

    async def all(self, tenant_id: str) -> list[StatuteDocument]: ...

    async def list_tenant_ids(self) -> list[str]:
        """Every distinct tenant_id with at least one statute on record —
        used by persistence/hydration.py to know which tenants' indexes to
        rebuild at startup, since there's no separate tenant registry to
        enumerate them from."""
        ...

    async def create_schema(self) -> None: ...

    async def close(self) -> None: ...


class InMemoryStatuteRepository:
    def __init__(self) -> None:
        self._statutes: dict[tuple[str, UUID], StatuteDocument] = {}

    async def add(self, statute: StatuteDocument, tenant_id: str) -> None:
        self._statutes[(tenant_id, statute.id)] = statute

    async def get(self, statute_id: UUID, tenant_id: str) -> StatuteDocument | None:
        return self._statutes.get((tenant_id, statute_id))

    async def list_by_citation(self, citation: str, tenant_id: str) -> list[StatuteDocument]:
        return [
            statute
            for (tid, _), statute in self._statutes.items()
            if tid == tenant_id and statute.citation == citation
        ]

    async def all(self, tenant_id: str) -> list[StatuteDocument]:
        return [statute for (tid, _), statute in self._statutes.items() if tid == tenant_id]

    async def list_tenant_ids(self) -> list[str]:
        return sorted({tid for tid, _ in self._statutes})

    async def create_schema(self) -> None:
        pass  # nothing to create for an in-memory dict

    async def close(self) -> None:
        pass  # nothing to release
