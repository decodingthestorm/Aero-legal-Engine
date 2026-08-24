"""SQLAlchemy-async-backed StatuteRepository.

Works against any DSN SQLAlchemy's async engine supports with the matching
driver installed — ``postgresql+asyncpg://`` in production
(docker-compose.yml runs Postgres; the ``postgres`` install extra pulls in
asyncpg), ``sqlite+aiosqlite://`` in this codebase's own test suite, since
there's no Postgres available to test against for real in the environment
this was built in. tests/integration/test_postgres_repository.py runs the
same repository against a real Postgres, but only under CI's ``postgres``
service container — see that file's skip condition.

This is a hard import of sqlalchemy at module level (needed for
``DeclarativeBase``/``Mapped``/``mapped_column`` at class-definition time,
not just inside a constructor like the knowledge_graph/ lazy backends),
which is exactly why ``InMemoryStatuteRepository`` lives in repository.py
instead of here — importing *that* module must never require SQLAlchemy to
be installed.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from legal_engine.core.models import (
    GeoBoundary,
    JurisdictionTier,
    SourceType,
    StatuteDocument,
    UserAccount,
)


class Base(DeclarativeBase):
    pass


class StatuteRecord(Base):
    __tablename__ = "statutes"

    # Composite primary key (tenant_id, id) rather than id alone: two
    # tenants adding statutes that happen to share the same UUID (via
    # StatuteDocument.model_copy, or — astronomically unlikely but not
    # worth relying on — a genuine uuid4 collision) must land as two
    # independent rows, not one row that the second write's session.merge()
    # silently overwrites. Deliberately not a field on StatuteDocument
    # itself: tenant_id is an access-control concern (who owns this record
    # in our system), not a fact about the statute the way applies_to is —
    # keeping it off the domain model means the same StatuteDocument shape
    # works identically regardless of which tenant is asking.
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(primary_key=True, index=True)
    source_type: Mapped[str] = mapped_column(nullable=False)
    jurisdiction_tier: Mapped[int] = mapped_column(nullable=False)
    citation: Mapped[str] = mapped_column(nullable=False, index=True)
    title: Mapped[str] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(nullable=True)
    effective_date: Mapped[datetime | None] = mapped_column(nullable=True)
    geo_lat_min: Mapped[float | None] = mapped_column(nullable=True)
    geo_lat_max: Mapped[float | None] = mapped_column(nullable=True)
    geo_lon_min: Mapped[float | None] = mapped_column(nullable=True)
    geo_lon_max: Mapped[float | None] = mapped_column(nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(nullable=False)
    # JSON-encoded list[str] rather than a join table: entity ids are plain
    # opaque strings everywhere else in the system (see
    # knowledge_graph/graph_service.py), so a normalized association table
    # would add real complexity (migrations, join queries) for a value this
    # system never queries *by* entity at the SQL level — only ever reads
    # back whole, to hand to GraphService.add_statute on startup rehydration.
    applies_to_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


def _to_domain(record: StatuteRecord) -> StatuteDocument:
    geo_boundary = None
    if record.geo_lat_min is not None:
        geo_boundary = GeoBoundary(
            lat_min=record.geo_lat_min,
            lat_max=record.geo_lat_max,
            lon_min=record.geo_lon_min,
            lon_max=record.geo_lon_max,
        )
    return StatuteDocument(
        id=record.id,
        source_type=SourceType(record.source_type),
        jurisdiction_tier=JurisdictionTier(record.jurisdiction_tier),
        citation=record.citation,
        title=record.title,
        text=record.text,
        source_url=record.source_url,
        effective_date=record.effective_date,
        geo_boundary=geo_boundary,
        ingested_at=record.ingested_at,
        applies_to=json.loads(record.applies_to_json),
    )


def _from_domain(statute: StatuteDocument, tenant_id: str) -> StatuteRecord:
    return StatuteRecord(
        id=statute.id,
        tenant_id=tenant_id,
        source_type=statute.source_type.value,
        jurisdiction_tier=statute.jurisdiction_tier.value,
        citation=statute.citation,
        title=statute.title,
        text=statute.text,
        source_url=statute.source_url,
        effective_date=statute.effective_date,
        geo_lat_min=statute.geo_boundary.lat_min if statute.geo_boundary else None,
        geo_lat_max=statute.geo_boundary.lat_max if statute.geo_boundary else None,
        geo_lon_min=statute.geo_boundary.lon_min if statute.geo_boundary else None,
        geo_lon_max=statute.geo_boundary.lon_max if statute.geo_boundary else None,
        ingested_at=statute.ingested_at,
        applies_to_json=json.dumps(statute.applies_to),
    )


class SqlAlchemyStatuteRepository:
    def __init__(self, dsn: str) -> None:
        self._engine: AsyncEngine = create_async_engine(dsn)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def add(self, statute: StatuteDocument, tenant_id: str) -> None:
        async with self._session_factory() as session:
            await session.merge(_from_domain(statute, tenant_id))
            await session.commit()

    async def get(self, statute_id: UUID, tenant_id: str) -> StatuteDocument | None:
        async with self._session_factory() as session:
            # Composite PK lookup, in (id, tenant_id) column-declaration
            # order. A statute existing under a *different* tenant is a
            # different primary key entirely, so this returns None for it
            # identically to a statute that doesn't exist at all — never
            # confirms even the existence of another tenant's data.
            record = await session.get(StatuteRecord, (statute_id, tenant_id))
            return _to_domain(record) if record is not None else None

    async def list_by_citation(self, citation: str, tenant_id: str) -> list[StatuteDocument]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(StatuteRecord).where(
                    StatuteRecord.citation == citation, StatuteRecord.tenant_id == tenant_id
                )
            )
            return [_to_domain(r) for r in result.scalars().all()]

    async def all(self, tenant_id: str) -> list[StatuteDocument]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(StatuteRecord).where(StatuteRecord.tenant_id == tenant_id)
            )
            return [_to_domain(r) for r in result.scalars().all()]

    async def list_tenant_ids(self) -> list[str]:
        async with self._session_factory() as session:
            result = await session.execute(select(StatuteRecord.tenant_id).distinct())
            return sorted(result.scalars().all())

    async def close(self) -> None:
        await self._engine.dispose()


class UserRecord(Base):
    __tablename__ = "users"

    # email is the primary key, globally — not scoped by tenant_id the
    # way StatuteRecord's PK is. See user_repository.py's module
    # docstring for why: a login only has an email + password to go on,
    # not a tenant_id, so account lookup at login time has to be global.
    # tenant_id is still stored (every account belongs to exactly one
    # tenant), just not part of the uniqueness boundary.
    email: Mapped[str] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(index=True)
    tenant_id: Mapped[str] = mapped_column(nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    # "owner"/"member" — see UserAccount's own docstring (core/models.py)
    # for what this does and doesn't gate.
    role: Mapped[str] = mapped_column(nullable=False, default="owner")
    email_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


def _user_to_domain(record: UserRecord) -> UserAccount:
    return UserAccount(
        id=record.id,
        tenant_id=record.tenant_id,
        email=record.email,
        password_hash=record.password_hash,
        role=record.role,
        email_verified=record.email_verified,
        created_at=record.created_at,
    )


def _user_from_domain(user: UserAccount) -> UserRecord:
    return UserRecord(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        password_hash=user.password_hash,
        role=user.role,
        email_verified=user.email_verified,
        created_at=user.created_at,
    )


class SqlAlchemyUserRepository:
    """Same DSN-driven, lazily-nothing-since-sqlalchemy-is-a-hard-import-
    here pattern as SqlAlchemyStatuteRepository above, in the same file
    since they're the same "sql" backend against the same database —
    just a second table (see UserRecord), not a second engine-building
    scheme."""

    def __init__(self, dsn: str) -> None:
        self._engine: AsyncEngine = create_async_engine(dsn)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def add(self, user: UserAccount) -> None:
        async with self._session_factory() as session:
            await session.merge(_user_from_domain(user))
            await session.commit()

    async def get_by_email(self, email: str) -> UserAccount | None:
        async with self._session_factory() as session:
            record = await session.get(UserRecord, email)
            return _user_to_domain(record) if record is not None else None

    async def list_by_tenant(self, tenant_id: str) -> list[UserAccount]:
        async with self._session_factory() as session:
            result = await session.execute(select(UserRecord).where(UserRecord.tenant_id == tenant_id))
            return [_user_to_domain(r) for r in result.scalars().all()]

    async def remove(self, email: str) -> None:
        async with self._session_factory() as session:
            record = await session.get(UserRecord, email)
            if record is not None:
                await session.delete(record)
                await session.commit()

    async def close(self) -> None:
        await self._engine.dispose()
