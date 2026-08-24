"""Runs SqlAlchemyUserRepository against a real Postgres.

Companion to test_postgres_repository.py, which covers the *statute*
repository — this file exists because that one never touched users, so
until now the entire user-account persistence layer (including
``list_by_tenant``/``remove``, added in v1.7.0 for member management) had
only ever run against SQLite.

That gap matters more here than the naming suggests. SQLite and Postgres
diverge on precisely what this repository does: ``UserRecord`` keys on a
*string* primary key rather than the statute table's composite UUID key,
so ``session.merge``'s upsert path is a different code path; ``remove``
issues a real DELETE; ``email_verified`` is a native BOOLEAN in Postgres
and an integer in SQLite; and ``created_at`` round-trips through
``TIMESTAMP WITHOUT TIME ZONE``, which discards the UTC offset the domain
model puts on it (see sql_repository.py's ``_as_utc``).

Skipped unless LEGAL_ENGINE_TEST_POSTGRES_DSN is set. CI's `postgres` job
(.github/workflows/ci.yml) sets it against a genuine `postgres` service
container, so this suite does run for real there — just never locally in
this environment.

Every test mints unique emails and tenant ids via uuid4: the users table
has a *global* primary key on email (not tenant-scoped — see
persistence/user_repository.py for why) and the CI container persists
across the whole session, so fixed values would collide between tests.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from legal_engine.core.models import UserAccount

_DSN = os.environ.get("LEGAL_ENGINE_TEST_POSTGRES_DSN")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        _DSN is None,
        reason="LEGAL_ENGINE_TEST_POSTGRES_DSN not set - no Postgres available to test against",
    ),
]


def _email() -> str:
    return f"pg-{uuid4()}@example.com"


def _tenant() -> str:
    return f"pg-tenant-{uuid4()}"


def _user(**overrides) -> UserAccount:
    defaults = {
        "tenant_id": _tenant(),
        "email": _email(),
        "password_hash": "pbkdf2_sha256$1$aa$bb",
    }
    defaults.update(overrides)
    return UserAccount(**defaults)


@pytest.fixture
async def repo():
    from legal_engine.persistence.sql_repository import SqlAlchemyUserRepository

    repository = SqlAlchemyUserRepository(_DSN)
    await repository.create_schema()
    yield repository
    await repository.close()


async def test_add_and_get_by_email_roundtrip_against_real_postgres(repo):
    user = _user()
    await repo.add(user)

    fetched = await repo.get_by_email(user.email)
    assert fetched.id == user.id
    assert fetched.tenant_id == user.tenant_id
    assert fetched.password_hash == user.password_hash


async def test_uuid_id_column_roundtrips_against_real_postgres(repo):
    """``UserRecord.id`` is an indexed UUID that is *not* the primary key
    — a different mapping situation from StatuteRecord's composite UUID
    PK, and the same class of thing test_postgres_repository.py exists to
    prove for statutes."""
    user = _user()
    await repo.add(user)

    fetched = await repo.get_by_email(user.email)
    assert fetched.id == user.id


async def test_email_verified_boolean_roundtrips_against_real_postgres(repo):
    """Native BOOLEAN in Postgres, integer 0/1 in SQLite."""
    verified = _user(email_verified=True)
    unverified = _user(email_verified=False)
    await repo.add(verified)
    await repo.add(unverified)

    assert (await repo.get_by_email(verified.email)).email_verified is True
    assert (await repo.get_by_email(unverified.email)).email_verified is False


async def test_member_role_roundtrips_against_real_postgres(repo):
    user = _user(role="member")
    await repo.add(user)
    assert (await repo.get_by_email(user.email)).role == "member"


async def test_created_at_comes_back_utc_aware_against_real_postgres(repo):
    """Postgres' TIMESTAMP WITHOUT TIME ZONE discards the offset, so the
    driver hands back a naive datetime; sql_repository._as_utc re-attaches
    UTC at the domain boundary. Without that, this value would compare
    unequal to what was stored and raise on any comparison against
    datetime.now(UTC)."""
    user = _user()
    await repo.add(user)

    fetched = await repo.get_by_email(user.email)
    assert fetched.created_at.tzinfo is not None
    assert fetched.created_at == user.created_at
    # and it's usable in a comparison against an aware "now" without raising
    assert fetched.created_at <= datetime.now(UTC)


async def test_add_upserts_on_the_string_primary_key_against_real_postgres(repo):
    """email is a *string* PK here, not the statute table's composite UUID
    key — session.merge takes a different path for it."""
    user = _user(password_hash="old-hash")
    await repo.add(user)
    await repo.add(user.model_copy(update={"password_hash": "new-hash"}))

    assert (await repo.get_by_email(user.email)).password_hash == "new-hash"


async def test_list_by_tenant_against_real_postgres(repo):
    tenant = _tenant()
    other_tenant = _tenant()
    a = _user(tenant_id=tenant)
    b = _user(tenant_id=tenant)
    c = _user(tenant_id=other_tenant)
    for user in (a, b, c):
        await repo.add(user)

    members = await repo.list_by_tenant(tenant)
    assert {m.email for m in members} == {a.email, b.email}


async def test_list_by_tenant_is_empty_for_an_unknown_tenant(repo):
    assert await repo.list_by_tenant(_tenant()) == []


async def test_remove_deletes_the_row_against_real_postgres(repo):
    user = _user()
    await repo.add(user)
    await repo.remove(user.email)

    assert await repo.get_by_email(user.email) is None


async def test_remove_missing_user_is_a_safe_noop_against_real_postgres(repo):
    await repo.remove(_email())  # should not raise


async def test_remove_leaves_the_rest_of_the_tenant_intact(repo):
    tenant = _tenant()
    a = _user(tenant_id=tenant)
    b = _user(tenant_id=tenant)
    await repo.add(a)
    await repo.add(b)

    await repo.remove(a.email)

    remaining = await repo.list_by_tenant(tenant)
    assert [m.email for m in remaining] == [b.email]


async def test_email_lookup_is_case_sensitive_against_real_postgres(repo):
    """Postgres text comparison is case-sensitive by default, so
    "Alice@..." and "alice@..." are two distinct primary keys. Worth
    pinning rather than assuming: api/routes/auth.py lowercases every
    email at the boundary (_validate_email_shape), and that normalization
    is the only thing standing between this behaviour and two accounts
    for the same person."""
    lower = f"pg-case-{uuid4()}@example.com"
    upper = lower.upper()
    await repo.add(_user(email=lower))

    assert await repo.get_by_email(lower) is not None
    assert await repo.get_by_email(upper) is None
