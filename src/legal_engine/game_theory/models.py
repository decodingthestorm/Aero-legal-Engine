"""Game-theoretic domain models layered on top of core.models' Actor/PayoffMatrix.

Actor, StrategyType, and PayoffMatrix live in legal_engine.core.models since
the API layer and the WAL also need to reference them. This module adds the
parameters specific to the statutory compliance game itself.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from legal_engine.core.models import Actor, PayoffMatrix, StrategyType  # noqa: F401  (re-exported)


class ComplianceGameParams(BaseModel):
    """Inputs to the deterrence-penalty calculation for a single actor/statute pair.

    Mirrors: Expected_Payoff(Evasion) = (1 - p_detect) * benefit - p_detect * P
             Payoff(Compliance) = -cost_compliance
    """

    benefit: float = Field(gt=0, description="Payoff to the actor from successful evasion")
    cost_compliance: float = Field(ge=0, description="Cost the actor bears by complying honestly")
    p_detect: float = Field(gt=0, le=1, description="Probability evasion is detected")

    @model_validator(mode="after")
    def _validate(self) -> ComplianceGameParams:
        if self.p_detect <= 0:
            raise ValueError("p_detect must be > 0: a zero-detection game has no finite deterrent")
        return self


class ConvexPenaltyParams(BaseModel):
    """Inputs to the strictly-convex penalty function P(x) = k*(x - x_limit)^2 + disgorgement."""

    k: float = Field(gt=0, description="Convexity coefficient; must be > 0 for strict convexity")
    x_limit: float = Field(description="Statutory boundary condition the actor exceeded")
    disgorgement: float = Field(default=0.0, ge=0, description="Profit disgorgement add-on")
