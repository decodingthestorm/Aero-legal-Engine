import pytest
from pydantic import ValidationError

from legal_engine.core.models import (
    GeoBoundary,
    JurisdictionTier,
    PayoffMatrix,
    SourceType,
    StatuteDocument,
    StrategyType,
)


def test_jurisdiction_tier_preemption_ordering():
    assert JurisdictionTier.FEDERAL.preempts(JurisdictionTier.STATE)
    assert JurisdictionTier.STATE.preempts(JurisdictionTier.MUNICIPAL)
    assert not JurisdictionTier.MUNICIPAL.preempts(JurisdictionTier.FEDERAL)
    assert JurisdictionTier.INTERNATIONAL_TREATY.preempts(JurisdictionTier.FEDERAL)


def test_geo_boundary_rejects_inverted_bounds():
    with pytest.raises(ValidationError):
        GeoBoundary(lat_min=10, lat_max=5, lon_min=0, lon_max=1)


def test_geo_boundary_accepts_valid_bounds():
    boundary = GeoBoundary(lat_min=5, lat_max=10, lon_min=-1, lon_max=1)
    assert boundary.lat_min == 5


def test_statute_document_defaults():
    doc = StatuteDocument(
        source_type=SourceType.MUNICIPAL_CODE,
        jurisdiction_tier=JurisdictionTier.MUNICIPAL,
        citation="Sec. 12.04.030",
        title="Zoning: Accessory Dwelling Units",
        text="No person shall...",
    )
    assert doc.id is not None
    assert doc.ingested_at is not None


def test_payoff_matrix_utility_lookup():
    matrix = PayoffMatrix(
        payoffs={"actor-1": {StrategyType.COMPLY: 10.0, StrategyType.EVADE: -5.0}}
    )
    assert matrix.utility("actor-1", StrategyType.COMPLY) == 10.0
    with pytest.raises(KeyError):
        matrix.utility("actor-1", StrategyType.EXPLOIT)
