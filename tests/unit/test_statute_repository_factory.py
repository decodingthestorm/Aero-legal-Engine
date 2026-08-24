import pytest

from legal_engine.core.config import settings
from legal_engine.persistence.factory import build_statute_repository
from legal_engine.persistence.repository import InMemoryStatuteRepository
from legal_engine.persistence.sql_repository import SqlAlchemyStatuteRepository


class TestBuildStatuteRepository:
    def test_default_backend_is_in_memory(self):
        assert isinstance(build_statute_repository(), InMemoryStatuteRepository)

    def test_sql_backend_builds_sqlalchemy_repository(self, monkeypatch):
        monkeypatch.setattr(settings, "statute_backend", "sql")
        monkeypatch.setattr(settings, "postgres_dsn", "sqlite+aiosqlite:///:memory:")
        repo = build_statute_repository()
        assert isinstance(repo, SqlAlchemyStatuteRepository)

    def test_sql_backend_with_missing_driver_fails_closed_with_install_hint(self, monkeypatch):
        """sqlalchemy itself is installed (needed to test against SQLite —
        see test_sql_repository.py), but asyncpg genuinely isn't in this
        environment (it's behind the `postgres` extra). Using the default
        postgres_dsn (postgresql+asyncpg://...) exercises the real "driver
        missing" failure mode: create_async_engine resolves and imports the
        driver immediately, not lazily, so this fails at construction, not
        at first connection — proving the factory's except clause has to
        wrap the constructor call too, not just the class import."""
        monkeypatch.setattr(settings, "statute_backend", "sql")
        with pytest.raises(ImportError, match=r"pip install 'legal-engine\[postgres\]'"):
            build_statute_repository()
