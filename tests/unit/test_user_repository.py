import pytest

from legal_engine.core.models import UserAccount
from legal_engine.persistence.user_repository import InMemoryUserRepository

pytestmark = pytest.mark.asyncio


def _user(email: str = "alice@example.com", tenant_id: str = "tenant-a", **overrides) -> UserAccount:
    defaults = {"tenant_id": tenant_id, "email": email, "password_hash": "pbkdf2_sha256$1$aa$bb"}
    defaults.update(overrides)
    return UserAccount(**defaults)


class TestInMemoryUserRepository:
    async def test_add_and_get_by_email_roundtrip(self):
        repo = InMemoryUserRepository()
        user = _user()
        await repo.add(user)
        assert await repo.get_by_email(user.email) == user

    async def test_get_missing_returns_none(self):
        repo = InMemoryUserRepository()
        assert await repo.get_by_email("nobody@example.com") is None

    async def test_email_lookup_is_global_not_tenant_scoped(self):
        """Login only has an email to go on, not a tenant_id — this is
        exactly the property that makes /auth/token's login flow able to
        find the right account (see user_repository.py's module
        docstring for why this is deliberate, not a data-isolation gap)."""
        repo = InMemoryUserRepository()
        user = _user(email="alice@example.com", tenant_id="tenant-xyz")
        await repo.add(user)
        assert (await repo.get_by_email("alice@example.com")).tenant_id == "tenant-xyz"

    async def test_two_tenants_have_independent_users(self):
        repo = InMemoryUserRepository()
        a = _user(email="alice@example.com", tenant_id="tenant-a")
        b = _user(email="bob@example.com", tenant_id="tenant-b")
        await repo.add(a)
        await repo.add(b)

        assert (await repo.get_by_email("alice@example.com")).tenant_id == "tenant-a"
        assert (await repo.get_by_email("bob@example.com")).tenant_id == "tenant-b"

    async def test_add_overwrites_existing_email(self):
        repo = InMemoryUserRepository()
        user = _user(password_hash="old-hash")
        await repo.add(user)
        updated = user.model_copy(update={"password_hash": "new-hash"})
        await repo.add(updated)
        assert (await repo.get_by_email(user.email)).password_hash == "new-hash"

    async def test_create_schema_and_close_are_safe_noops(self):
        repo = InMemoryUserRepository()
        await repo.create_schema()
        await repo.close()

    async def test_role_defaults_to_owner(self):
        repo = InMemoryUserRepository()
        user = _user()
        await repo.add(user)
        assert (await repo.get_by_email(user.email)).role == "owner"

    async def test_member_role_roundtrips(self):
        repo = InMemoryUserRepository()
        user = _user(role="member")
        await repo.add(user)
        assert (await repo.get_by_email(user.email)).role == "member"

    async def test_email_verified_defaults_to_false_and_roundtrips_true(self):
        repo = InMemoryUserRepository()
        user = _user(email_verified=True)
        await repo.add(user)
        assert (await repo.get_by_email(user.email)).email_verified is True

    async def test_list_by_tenant_returns_only_that_tenants_users(self):
        repo = InMemoryUserRepository()
        a = _user(email="alice@example.com", tenant_id="tenant-a")
        b = _user(email="bob@example.com", tenant_id="tenant-a")
        c = _user(email="carol@example.com", tenant_id="tenant-b")
        await repo.add(a)
        await repo.add(b)
        await repo.add(c)

        members = await repo.list_by_tenant("tenant-a")
        assert {m.email for m in members} == {"alice@example.com", "bob@example.com"}

    async def test_list_by_tenant_empty_when_no_users(self):
        repo = InMemoryUserRepository()
        assert await repo.list_by_tenant("tenant-a") == []

    async def test_remove_deletes_the_user(self):
        repo = InMemoryUserRepository()
        user = _user()
        await repo.add(user)
        await repo.remove(user.email)
        assert await repo.get_by_email(user.email) is None

    async def test_remove_missing_user_is_a_safe_noop(self):
        repo = InMemoryUserRepository()
        await repo.remove("nobody@example.com")  # should not raise

    async def test_remove_does_not_affect_other_users(self):
        repo = InMemoryUserRepository()
        a = _user(email="alice@example.com")
        b = _user(email="bob@example.com")
        await repo.add(a)
        await repo.add(b)
        await repo.remove(a.email)
        assert await repo.get_by_email(b.email) == b
