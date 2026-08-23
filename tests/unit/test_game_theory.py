import pytest
from pydantic import ValidationError

from legal_engine.core.exceptions import NoDominantStrategyError
from legal_engine.core.models import StrategyType
from legal_engine.game_theory.mechanism import (
    incentive_compatibility,
    individual_rationality,
    satisfies_mechanism_constraints,
)
from legal_engine.game_theory.models import ComplianceGameParams, ConvexPenaltyParams
from legal_engine.game_theory.nash_solver import (
    find_dominant_strategy,
    is_compliance_dominant_for_actor,
)
from legal_engine.game_theory.penalty_optimizer import (
    calibrate_convexity_for_floor,
    convex_penalty,
    is_compliance_dominant,
    minimum_deterrent_penalty,
    solve_minimum_penalty,
)
from legal_engine.game_theory.trembling_hand import check_trembling_hand_perfect


class TestPenaltyOptimizer:
    def test_zero_p_detect_rejected(self):
        with pytest.raises(ValidationError):
            ComplianceGameParams(benefit=100, cost_compliance=10, p_detect=0)

    def test_minimum_penalty_makes_compliance_dominant(self):
        params = ComplianceGameParams(benefit=1000, cost_compliance=50, p_detect=0.3)
        penalty = solve_minimum_penalty(params)
        assert is_compliance_dominant(params, penalty)

    def test_penalty_at_threshold_is_not_strictly_dominant(self):
        params = ComplianceGameParams(benefit=1000, cost_compliance=50, p_detect=0.3)
        threshold = minimum_deterrent_penalty(params)
        assert not is_compliance_dominant(params, threshold)

    def test_penalty_below_threshold_leaves_evasion_attractive(self):
        params = ComplianceGameParams(benefit=1000, cost_compliance=50, p_detect=0.3)
        threshold = minimum_deterrent_penalty(params)
        assert not is_compliance_dominant(params, threshold - 10)

    def test_convex_penalty_is_strictly_convex_in_deviation(self):
        penalty_params = ConvexPenaltyParams(k=2.0, x_limit=100.0)
        assert convex_penalty(100.0, penalty_params) == 0.0
        assert convex_penalty(110.0, penalty_params) == 200.0
        assert convex_penalty(90.0, penalty_params) == 200.0

    def test_calibrate_convexity_meets_floor(self):
        penalty_params = ConvexPenaltyParams(k=0.01, x_limit=100.0)
        calibrated = calibrate_convexity_for_floor(120.0, penalty_params, floor=5000.0)
        assert convex_penalty(120.0, calibrated) >= 5000.0

    def test_calibrate_convexity_no_deviation_raises(self):
        penalty_params = ConvexPenaltyParams(k=1.0, x_limit=100.0)
        with pytest.raises(NoDominantStrategyError):
            calibrate_convexity_for_floor(100.0, penalty_params, floor=10.0)


class TestNashSolver:
    def test_finds_dominant_strategy(self, compliant_payoff_matrix):
        assert find_dominant_strategy("landlord-1", compliant_payoff_matrix) == StrategyType.COMPLY

    def test_is_compliance_dominant(self, compliant_payoff_matrix):
        assert is_compliance_dominant_for_actor("landlord-1", compliant_payoff_matrix)


class TestMechanism:
    def test_individual_rationality_satisfied(self, sample_actor, compliant_payoff_matrix):
        assert individual_rationality(sample_actor, compliant_payoff_matrix, StrategyType.COMPLY)

    def test_individual_rationality_violated_below_reservation(self, compliant_payoff_matrix):
        from legal_engine.core.models import Actor

        strict_actor = Actor(id="landlord-1", name="X", reservation_utility=0.0)
        assert not individual_rationality(strict_actor, compliant_payoff_matrix, StrategyType.COMPLY)

    def test_incentive_compatibility(self, compliant_payoff_matrix):
        assert incentive_compatibility("landlord-1", compliant_payoff_matrix, StrategyType.COMPLY)
        assert not incentive_compatibility("landlord-1", compliant_payoff_matrix, StrategyType.EVADE)

    def test_satisfies_mechanism_constraints(self, sample_actor, compliant_payoff_matrix):
        assert satisfies_mechanism_constraints(sample_actor, compliant_payoff_matrix, StrategyType.COMPLY)


class TestTremblingHand:
    def test_strictly_dominant_strategy_is_trembling_hand_perfect(self, compliant_payoff_matrix):
        result = check_trembling_hand_perfect(
            "landlord-1", StrategyType.COMPLY, compliant_payoff_matrix, epsilon_max=0.05
        )
        assert result.is_perfect
        assert result.worst_case_margin > 0

    def test_dominated_strategy_is_not_trembling_hand_perfect(self, compliant_payoff_matrix):
        result = check_trembling_hand_perfect(
            "landlord-1", StrategyType.EVADE, compliant_payoff_matrix, epsilon_max=0.05
        )
        assert not result.is_perfect
