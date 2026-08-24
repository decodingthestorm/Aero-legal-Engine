"""Settings-driven factory for the StatuteRepository, mirroring
knowledge_graph/factory.py's pattern for the graph/vector/embedder
backends.

Unlike those, "sql" isn't a lazily-imported optional class living
alongside the default in the same module — importing sql_repository.py at
all requires SQLAlchemy to be installed (see that module's docstring), so
the import itself is deferred to inside this function's "sql" branch.

Both the import *and* the construction below are wrapped in one try/except:
SQLAlchemy itself might be installed (as it is in this codebase's own test
suite, which needs it to test against SQLite) while the driver a specific
DSN needs is not — ``create_async_engine("postgresql+asyncpg://...")``
resolves and imports the asyncpg driver immediately, not lazily at first
connection, and asyncpg genuinely isn't installed unless the ``postgres``
extra is. Catching only the import and not the construction would let that
second failure mode escape as a raw, unhelpful traceback.
"""

from __future__ import annotations

from legal_engine.core.config import settings
from legal_engine.persistence.repository import InMemoryStatuteRepository, StatuteRepository


def build_statute_repository() -> StatuteRepository:
    if settings.statute_backend == "sql":
        try:
            from legal_engine.persistence.sql_repository import SqlAlchemyStatuteRepository

            return SqlAlchemyStatuteRepository(settings.postgres_dsn)
        except Exception as exc:
            raise ImportError(
                "The 'sql' statute backend requires: pip install 'legal-engine[postgres]' "
                f"(underlying error: {exc.__class__.__name__}: {exc})"
            ) from exc
    return InMemoryStatuteRepository()
