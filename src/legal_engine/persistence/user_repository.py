"""The durable, queryable system-of-record for registered users.

Email is globally unique (not scoped by tenant, unlike StatuteRepository's
tenant-scoped lookups) — deliberately, not an oversight: POST /auth/token's
login flow only has an email + password to go on, not a tenant_id (a
client doesn't know its own tenant_id until *after* it's authenticated),
so resolving "which account does this email belong to" has to be a global
lookup. That's a property of the login credential itself, not a breach of
the data-isolation guarantee documented in persistence/repository.py —
that guarantee is about tenant *data* (statutes, graph edges, vector
entries) being invisible across tenants, not about whether a login
system can find the one account an email maps to.

Every tenant has exactly one user in this version — POST /auth/register
always provisions a brand-new tenant alongside its first user (see
api/routes/auth.py's own docstring for why inviting a second user into an
*existing* tenant is out of scope here) — so there's no separate "list
users in a tenant" method to build yet.

``InMemoryUserRepository`` lives here (no SQLAlchemy import, always
available) rather than alongside ``SqlAlchemyUserRepository`` in
sql_repository.py, for the identical reason repository.py's own
docstring gives for InMemoryStatuteRepository: importing this module
should never require SQLAlchemy to be installed.
"""

from __future__ import annotations

from typing import Protocol

from legal_engine.core.models import UserAccount


class UserRepository(Protocol):
    async def add(self, user: UserAccount) -> None: ...

    async def get_by_email(self, email: str) -> UserAccount | None: ...

    async def create_schema(self) -> None: ...

    async def close(self) -> None: ...


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[str, UserAccount] = {}  # email -> account

    async def add(self, user: UserAccount) -> None:
        self._users[user.email] = user

    async def get_by_email(self, email: str) -> UserAccount | None:
        return self._users.get(email)

    async def create_schema(self) -> None:
        pass  # nothing to create for an in-memory dict

    async def close(self) -> None:
        pass  # nothing to release
