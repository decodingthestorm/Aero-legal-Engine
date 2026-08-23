"""Selten's Trembling Hand Perfect Equilibrium refinement for the compliance game.

A pure-strategy equilibrium is "trembling-hand perfect" if it remains a best
response even when every actor has a small independent chance (a "tremble")
of playing an unintended strategy by mistake. We check this the direct way:
for a grid of tremble probabilities epsilon in (0, epsilon_max], compute the
actor's expected utility of the candidate strategy under the perturbed
(fully-mixed) profile of *other* actors, and confirm no alternative strategy
does better at any sampled epsilon.

This is a numeric sampling check, not a closed-form proof that the property
holds for literally every epsilon in the interval — the underlying payoff
functions here are continuous and typically monotonic in epsilon, so a fine
grid is a reasonable approximation, but it is still an approximation and
that limitation should stay visible to callers rather than being papered
over with a bare boolean.
"""

from __future__ import annotations

from dataclasses import dataclass

from legal_engine.core.models import PayoffMatrix, StrategyType


@dataclass
class TremblingHandResult:
    is_perfect: bool
    checked_epsilons: list[float]
    worst_case_margin: float
    """min over checked epsilons of (candidate utility - best alternative utility).
    Positive means the candidate strictly beat every alternative at every
    sampled epsilon; non-positive means at least one epsilon broke it."""


def check_trembling_hand_perfect(
    actor_id: str,
    candidate_strategy: StrategyType,
    payoff_matrix: PayoffMatrix,
    epsilon_max: float = 0.05,
    num_samples: int = 20,
) -> TremblingHandResult:
    if not (0 < epsilon_max <= 1):
        raise ValueError("epsilon_max must be in (0, 1]")

    all_strategies = list(StrategyType)
    alternatives = [s for s in all_strategies if s != candidate_strategy]

    epsilons = [epsilon_max * (i + 1) / num_samples for i in range(num_samples)]

    worst_margin = float("inf")
    for epsilon in epsilons:
        # Perturbed utility: the actor still intends `candidate_strategy` but,
        # with probability epsilon total, trembles into a uniformly random
        # alternative instead.
        candidate_utility = (1 - epsilon) * payoff_matrix.utility(
            actor_id, candidate_strategy
        ) + epsilon * _uniform_average(actor_id, alternatives, payoff_matrix)

        for alt in alternatives:
            other_alts = [s for s in all_strategies if s != alt]
            alt_utility = (1 - epsilon) * payoff_matrix.utility(
                actor_id, alt
            ) + epsilon * _uniform_average(actor_id, other_alts, payoff_matrix)
            worst_margin = min(worst_margin, candidate_utility - alt_utility)

    return TremblingHandResult(
        is_perfect=worst_margin > 0,
        checked_epsilons=epsilons,
        worst_case_margin=worst_margin,
    )


def _uniform_average(actor_id: str, strategies: list[StrategyType], payoff_matrix: PayoffMatrix) -> float:
    if not strategies:
        return 0.0
    return sum(payoff_matrix.utility(actor_id, s) for s in strategies) / len(strategies)
