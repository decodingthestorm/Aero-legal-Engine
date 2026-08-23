"""Computes the minimum penalty that makes honest compliance a dominant strategy.

Derivation (from the compliance game's expected-payoff inequality):

    Expected_Payoff(Evasion) < Payoff(Compliance)
    (1 - p_detect) * benefit - p_detect * P  <  -cost_compliance
    P  >  [(1 - p_detect) * benefit + cost_compliance] / p_detect

Any P at or below that threshold leaves evasion weakly attractive; the
optimizer returns the threshold plus a small margin so the caller gets a
penalty that is strictly, not just marginally, deterrent.
"""

from __future__ import annotations

from legal_engine.core.exceptions import NoDominantStrategyError
from legal_engine.game_theory.models import ComplianceGameParams, ConvexPenaltyParams

_DEFAULT_MARGIN = 1e-6


def minimum_deterrent_penalty(params: ComplianceGameParams) -> float:
    """The infimum penalty threshold P* above which compliance strictly dominates evasion."""
    return ((1 - params.p_detect) * params.benefit + params.cost_compliance) / params.p_detect


def solve_minimum_penalty(params: ComplianceGameParams, margin: float = _DEFAULT_MARGIN) -> float:
    """The minimum penalty that actually achieves strict dominance (threshold + margin)."""
    if margin <= 0:
        raise ValueError("margin must be > 0; a penalty exactly at the threshold is not strict")
    return minimum_deterrent_penalty(params) + margin


def is_compliance_dominant(params: ComplianceGameParams, penalty: float) -> bool:
    """Whether the given penalty makes compliance strictly better than evasion in expectation."""
    expected_evasion_payoff = (1 - params.p_detect) * params.benefit - params.p_detect * penalty
    compliance_payoff = -params.cost_compliance
    return expected_evasion_payoff < compliance_payoff


def convex_penalty(x_actual: float, penalty_params: ConvexPenaltyParams) -> float:
    """P(x) = k * (x_actual - x_limit)^2 + disgorgement. Strictly convex in x_actual since k > 0."""
    deviation = x_actual - penalty_params.x_limit
    return penalty_params.k * deviation**2 + penalty_params.disgorgement


def calibrate_convexity_for_floor(
    x_actual: float, penalty_params: ConvexPenaltyParams, floor: float
) -> ConvexPenaltyParams:
    """Return penalty params with k rescaled so convex_penalty(x_actual, ...) >= floor.

    Useful when the game-theoretic minimum penalty (a scalar) needs to be
    expressed as a convex function of the observed deviation rather than a
    flat number: at the actor's realized ``x_actual`` the convex curve must
    clear the deterrence floor.
    """
    deviation = x_actual - penalty_params.x_limit
    if deviation == 0:
        raise NoDominantStrategyError(
            "x_actual equals x_limit: no deviation to penalize, so no finite k can "
            "produce a positive convex penalty at this point"
        )
    required_k = max(floor - penalty_params.disgorgement, 0.0) / deviation**2
    return penalty_params.model_copy(update={"k": max(required_k, penalty_params.k)})
