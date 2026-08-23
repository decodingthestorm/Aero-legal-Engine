"""Shared fixtures for the Legal Engine test suite."""

from __future__ import annotations

import pytest

from legal_engine.core.models import Actor, PayoffMatrix, StrategyType


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
