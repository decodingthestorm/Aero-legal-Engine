"""Mechanism-design constraints: Individual Rationality and Incentive Compatibility.

IR:  u_i(s_i*) >= u_bar_i           — the actor is at least as well off participating
                                       (complying) as taking their outside option.
IC:  u_i(s_i*, s_-i*) >= u_i(s_i, s_-i*)  for all alternative s_i — no unilateral
                                       deviation improves the actor's payoff.
"""

from __future__ import annotations

from legal_engine.core.models import Actor, PayoffMatrix, StrategyType


def individual_rationality(
    actor: Actor, payoff_matrix: PayoffMatrix, chosen_strategy: StrategyType
) -> bool:
    """u_i(s_i*) >= u_bar_i"""
    return payoff_matrix.utility(actor.id, chosen_strategy) >= actor.reservation_utility


def incentive_compatibility(
    actor_id: str,
    payoff_matrix: PayoffMatrix,
    chosen_strategy: StrategyType,
) -> bool:
    """u_i(s_i*) >= u_i(s_i) for every alternative strategy s_i."""
    chosen_utility = payoff_matrix.utility(actor_id, chosen_strategy)
    return all(
        chosen_utility >= payoff_matrix.utility(actor_id, alt)
        for alt in StrategyType
        if alt != chosen_strategy
    )


def satisfies_mechanism_constraints(
    actor: Actor, payoff_matrix: PayoffMatrix, chosen_strategy: StrategyType
) -> bool:
    return individual_rationality(actor, payoff_matrix, chosen_strategy) and incentive_compatibility(
        actor.id, payoff_matrix, chosen_strategy
    )
