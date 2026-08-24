import pytest

from legal_engine.core.config import settings
from legal_engine.persistence.factory import build_user_repository
from legal_engine.persistence.sql_repository import SqlAlchemyUserRepository
from legal_engine.persistence.user_repository import InMemoryUserRepository


class TestBuildUserRepository:
    def test_default_backend_is_in_memory(self):
        assert isinstance(build_user_repository(), InMemoryUserRepository)

    def test_sql_backend_builds_sqlalchemy_repository(self, monkeypatch):
        monkeypatch.setattr(settings, "user_backend", "sql")
        monkeypatch.setattr(settings, "postgres_dsn", "sqlite+aiosqlite:///:memory:")
        repo = build_user_repository()
        assert isinstance(repo, SqlAlchemyUserRepository)

    def test_sql_backend_with_missing_driver_fails_closed_with_install_hint(self, monkeypatch):
        """Same real failure mode as
        test_statute_repository_factory.py's identically-named test:
        asyncpg genuinely isn't installed in this environment, and
        create_async_engine resolves/imports the driver immediately at
        construction, not lazily at first connection."""
        monkeypatch.setattr(settings, "user_backend", "sql")
        with pytest.raises(ImportError, match=r"pip install 'legal-engine\[postgres\]'"):
            build_user_repository()
