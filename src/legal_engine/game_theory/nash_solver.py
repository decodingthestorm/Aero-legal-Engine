"""Dominant-strategy solver for the statutory compliance game.

Note on scope: PayoffMatrix (core/models.py) gives each actor's utility as a
function of their own strategy only — it does not model utility as a
function of the full joint action profile the way a general N-player
normal-form game would. That matches how the rest of this subsystem frames
the problem: penalty_optimizer.py derives a deterrence penalty from a fixed
detection probability, i.e. each actor is an independent expected-utility
maximizer against a fixed environment, not a strategic opponent whose payoff
depends on what other actors do. A "dominant strategy" here is therefore
just "the actor's utility-maximizing strategy" — which is what dominance
collapses to when payoffs don't depend on others' actions. Modeling genuine
strategic interaction between actors (e.g. collusion) would require
extending PayoffMatrix to be keyed by joint action profiles, which is out of
scope for Phase 1.
"""

from __future__ import annotations

from legal_engine.core.models import PayoffMatrix, StrategyType


def find_dominant_strategy(actor_id: str, payoff_matrix: PayoffMatrix) -> StrategyType:
    strategies = payoff_matrix.payoffs[actor_id]
    return max(strategies, key=lambda s: strategies[s])


def find_all_dominant_strategies(payoff_matrix: PayoffMatrix) -> dict[str, StrategyType]:
    return {actor_id: find_dominant_strategy(actor_id, payoff_matrix) for actor_id in payoff_matrix.payoffs}


def is_compliance_dominant_for_actor(actor_id: str, payoff_matrix: PayoffMatrix) -> bool:
    return find_dominant_strategy(actor_id, payoff_matrix) == StrategyType.COMPLY
