"""Exercises SqlAlchemyUserRepository for real against SQLite (via
aiosqlite) — same "no Postgres available in this environment" situation
as test_sql_repository.py; see that file's own docstring.
"""

from __future__ import annotations

import pytest

from legal_engine.core.models import UserAccount
from legal_engine.persistence.sql_repository import SqlAlchemyUserRepository

pytestmark = pytest.mark.asyncio


def _user(email: str = "alice@example.com", tenant_id: str = "tenant-a", **overrides) -> UserAccount:
    defaults = {"tenant_id": tenant_id, "email": email, "password_hash": "pbkdf2_sha256$1$aa$bb"}
    defaults.update(overrides)
    return UserAccount(**defaults)


@pytest.fixture
async def repo(tmp_path):
    dsn = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    repository = SqlAlchemyUserRepository(dsn)
    await repository.create_schema()
    yield repository
    await repository.close()


class TestSqlAlchemyUserRepository:
    async def test_add_and_get_by_email_roundtrip(self, repo):
        user = _user()
        await repo.add(user)

        fetched = await repo.get_by_email(user.email)
        assert fetched.id == user.id
        assert fetched.tenant_id == user.tenant_id
        assert fetched.email == user.email
        assert fetched.password_hash == user.password_hash

    async def test_get_missing_returns_none(self, repo):
        assert await repo.get_by_email("nobody@example.com") is None

    async def test_email_lookup_is_global_not_tenant_scoped(self, repo):
        user = _user(email="alice@example.com", tenant_id="tenant-xyz")
        await repo.add(user)
        fetched = await repo.get_by_email("alice@example.com")
        assert fetched.tenant_id == "tenant-xyz"

    async def test_two_tenants_have_independent_users(self, repo):
        a = _user(email="alice@example.com", tenant_id="tenant-a")
        b = _user(email="bob@example.com", tenant_id="tenant-b")
        await repo.add(a)
        await repo.add(b)

        assert (await repo.get_by_email("alice@example.com")).tenant_id == "tenant-a"
        assert (await repo.get_by_email("bob@example.com")).tenant_id == "tenant-b"

    async def test_add_upserts_existing_email(self, repo):
        user = _user(password_hash="old-hash")
        await repo.add(user)
        await repo.add(user.model_copy(update={"password_hash": "new-hash"}))

        fetched = await repo.get_by_email(user.email)
        assert fetched.password_hash == "new-hash"

    async def test_data_persists_across_separate_repository_instances(self, tmp_path):
        dsn = f"sqlite+aiosqlite:///{tmp_path}/durable.db"

        first = SqlAlchemyUserRepository(dsn)
        await first.create_schema()
        user = _user()
        await first.add(user)
        await first.close()

        second = SqlAlchemyUserRepository(dsn)
        fetched = await second.get_by_email(user.email)
        assert fetched is not None
        assert fetched.tenant_id == user.tenant_id
        await second.close()
