"""Game-theoretic simulation endpoints.

Exposes game_theory.penalty_optimizer's deterrence-penalty math and
game_theory.trembling_hand's equilibrium-refinement check as a
request/response API — this is what the ui/ SimulationCard component will
eventually chart against.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from legal_engine.core.models import PayoffMatrix, StrategyType
from legal_engine.game_theory.models import ComplianceGameParams, ConvexPenaltyParams
from legal_engine.game_theory.penalty_optimizer import (
    convex_penalty,
    is_compliance_dominant,
    minimum_deterrent_penalty,
    solve_minimum_penalty,
)
from legal_engine.game_theory.trembling_hand import check_trembling_hand_perfect

router = APIRouter()


class PenaltyRequest(BaseModel):
    benefit: float = Field(gt=0)
    cost_compliance: float = Field(ge=0)
    p_detect: float = Field(gt=0, le=1)


class PenaltyResponse(BaseModel):
    minimum_deterrent_penalty: float
    recommended_penalty: float
    recommended_penalty_is_dominant: bool


@router.post("/penalty", response_model=PenaltyResponse)
async def compute_penalty(request: PenaltyRequest) -> PenaltyResponse:
    params = ComplianceGameParams(**request.model_dump())
    threshold = minimum_deterrent_penalty(params)
    recommended = solve_minimum_penalty(params)
    return PenaltyResponse(
        minimum_deterrent_penalty=threshold,
        recommended_penalty=recommended,
        recommended_penalty_is_dominant=is_compliance_dominant(params, recommended),
    )


class ConvexPenaltyCurveRequest(BaseModel):
    k: float = Field(gt=0)
    x_limit: float
    disgorgement: float = Field(default=0.0, ge=0)
    sample_points: list[float]


@router.post("/penalty-curve", response_model=dict[str, float])
async def compute_penalty_curve(request: ConvexPenaltyCurveRequest) -> dict[str, float]:
    params = ConvexPenaltyParams(k=request.k, x_limit=request.x_limit, disgorgement=request.disgorgement)
    return {str(x): convex_penalty(x, params) for x in request.sample_points}


class TremblingHandRequest(BaseModel):
    actor_id: str
    candidate_strategy: StrategyType
    payoff_matrix: PayoffMatrix
    epsilon_max: float = Field(default=0.05, gt=0, le=1)


class TremblingHandResponse(BaseModel):
    is_perfect: bool
    worst_case_margin: float


@router.post("/trembling-hand", response_model=TremblingHandResponse)
async def check_trembling_hand(request: TremblingHandRequest) -> TremblingHandResponse:
    result = check_trembling_hand_perfect(
        request.actor_id, request.candidate_strategy, request.payoff_matrix, request.epsilon_max
    )
    return TremblingHandResponse(is_perfect=result.is_perfect, worst_case_margin=result.worst_case_margin)
