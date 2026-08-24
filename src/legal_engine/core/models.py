"""Pydantic v2 schemas shared across ingestion, formal logic, game theory, and the knowledge graph."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JurisdictionTier(int, Enum):
    """Article VI Supremacy Clause ordering. Lower value == higher precedence."""

    INTERNATIONAL_TREATY = 0
    FEDERAL = 1
    STATE = 2
    COUNTY = 3
    MUNICIPAL = 4

    def preempts(self, other: JurisdictionTier) -> bool:
        return self.value < other.value


class SourceType(str, Enum):
    MUNICIPAL_CODE = "municipal_code"
    STATE_STATUTE = "state_statute"
    FEDERAL_CODE = "federal_code"
    INTERNATIONAL_TREATY = "international_treaty"
    JUDICIAL_PRECEDENT = "judicial_precedent"


class GeoBoundary(BaseModel):
    """Bounding box for spatially-scoped statutes (zoning, maritime boundaries, etc.)."""

    lat_min: float = Field(ge=-90, le=90)
    lat_max: float = Field(ge=-90, le=90)
    lon_min: float = Field(ge=-180, le=180)
    lon_max: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _check_ordering(self) -> GeoBoundary:
        if self.lat_min > self.lat_max:
            raise ValueError("lat_min must be <= lat_max")
        if self.lon_min > self.lon_max:
            raise ValueError("lon_min must be <= lon_max")
        return self


class StatuteDocument(BaseModel):
    """A single ingested legal document (statute, ordinance, regulation, treaty article)."""

    model_config = ConfigDict(frozen=False)

    id: UUID = Field(default_factory=uuid4)
    source_type: SourceType
    jurisdiction_tier: JurisdictionTier
    citation: str
    title: str
    text: str
    source_url: str | None = None
    effective_date: datetime | None = None
    geo_boundary: GeoBoundary | None = None
    ingested_at: datetime = Field(default_factory=_utcnow)
    applies_to: list[str] = Field(default_factory=list)
    """Entity ids this statute is tied to in the knowledge graph (see
    knowledge_graph.graph_service.GraphService.add_statute). Persisted here
    (rather than only passed alongside the statute at add-time) so
    persistence.factory's startup reindex can rebuild GraphService's
    statute-to-entity edges from StatuteRepository alone — without this
    field, that association would exist nowhere durable to rebuild from."""


class StrategyType(str, Enum):
    COMPLY = "comply"
    EXPLOIT = "exploit"
    EVADE = "evade"


class Actor(BaseModel):
    """A player in the statutory compliance game."""

    id: str
    name: str
    reservation_utility: float = 0.0
    """Minimum utility (u_bar_i) the actor must receive to participate (Individual Rationality)."""


class PayoffMatrix(BaseModel):
    """Utility of each (actor, strategy) pair. Sparse dict keyed by (actor_id, strategy)."""

    payoffs: dict[str, dict[StrategyType, float]]

    def utility(self, actor_id: str, strategy: StrategyType) -> float:
        return self.payoffs[actor_id][strategy]


class ProofResult(BaseModel):
    """Result of a Z3 SMT-LIB2 satisfiability check on a compiled EPR formula."""

    satisfiable: bool
    unsat_core: list[str] = Field(default_factory=list)
    counterexample: dict[str, str] | None = None
    elapsed_ms: float
    timed_out: bool = False


class WALEntry(BaseModel):
    """One append-only, hash-chained, Ed25519-signed write-ahead log entry."""

    sequence: int
    prev_hash: str
    payload_hash: str
    signature: str
    event_type: str
    payload: dict
    timestamp: datetime = Field(default_factory=_utcnow)
