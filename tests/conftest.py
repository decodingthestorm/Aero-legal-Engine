"""Shared fixtures for the Legal Engine test suite."""

from __future__ import annotations

import pytest

from legal_engine.core.config import settings
from legal_engine.core.models import Actor, PayoffMatrix, StrategyType


@pytest.fixture(autouse=True)
def _isolate_wal_path(tmp_path, monkeypatch):
    """Any test that spins up the real app (``TestClient(app)``) runs
    api/main.py's lifespan, which builds a WriteAheadLog rooted at
    settings.wal_path (default "data/wal", a real path relative to the
    repo root) on every startup. Without this, the test suite would write
    real files into the actual project directory as a side effect of
    running tests — and worse, since compliance/consent.py's tenant
    acceptance state is persisted there, one test's "tenant accepted the
    disclaimer" would silently leak into every other test (and every other
    pytest invocation) via that shared file. Autouse and function-scoped
    (via tmp_path) so every single test gets an empty, private WAL
    directory without having to opt in.
    """
    monkeypatch.setattr(settings, "wal_path", str(tmp_path / "wal"))


@pytest.fixture
def compliant_payoff_matrix() -> PayoffMatrix:
    """A payoff matrix where COMPLY strictly dominates for actor 'landlord-1'."""
    return PayoffMatrix(
        payoffs={
            "landlord-1": {
                StrategyType.COMPLY: -50.0,
                StrategyType.EXPLOIT: -75.0,
                StrategyType.EVADE: -200.0,
            }
        }
    )


@pytest.fixture
def sample_actor() -> Actor:
    return Actor(id="landlord-1", name="Example Landlord LLC", reservation_utility=-100.0)
