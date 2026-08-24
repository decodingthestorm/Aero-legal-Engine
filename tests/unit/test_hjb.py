"""Checks the HJB finite-difference sweep against the exact LQ solution.

The load-bearing test is TestConvergence: agreement to a fixed tolerance
can be a coincidence of one grid, but the error falling at the
second-order rate central differences are supposed to give is much harder
to get by accident. A sign error or a mis-centred stencil typically still
converges — just at first order — so the rate catches things a tolerance
does not.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from legal_engine.game_theory.hjb import (
    HjbError,
    LqRegulatorProblem,
    optimal_control_lq,
    riccati_solution,
    solve_hjb,
)


def _problem(**overrides) -> LqRegulatorProblem:
    defaults = {
        "drift": -0.1,
        "control_gain": 1.0,
        "volatility": 0.3,
        "state_cost": 1.0,
        "control_cost": 1.0,
        "terminal_cost": 0.5,
        "horizon": 1.0,
    }
    defaults.update(overrides)
    return LqRegulatorProblem(**defaults)


def _max_interior_error(problem, grid_points, window=2.0):
    solution = solve_hjb(problem, grid_points=grid_points)
    p, s = riccati_solution(problem, 0.0)
    exact = p * solution.states**2 + s
    interior = np.abs(solution.states) <= window
    return float(np.max(np.abs(solution.values[interior] - exact[interior])))


class TestRiccatiClosedForm:
    def test_terminal_condition(self):
        problem = _problem(terminal_cost=0.7)
        p, s = riccati_solution(problem, problem.horizon)
        assert p == pytest.approx(0.7)
        assert s == pytest.approx(0.0)

    def test_p_is_positive_over_the_horizon(self):
        """A negative P would mean the regulator is rewarded for a larger
        compliance gap."""
        problem = _problem()
        for t in np.linspace(0.0, problem.horizon, 11):
            assert riccati_solution(problem, float(t))[0] > 0.0

    def test_no_noise_means_no_offset(self):
        """S integrates sigma^2 * P, so it vanishes exactly when the
        process is deterministic."""
        assert riccati_solution(_problem(volatility=0.0), 0.0)[1] == pytest.approx(0.0)

    def test_noise_raises_the_value_but_not_the_policy(self):
        """sigma enters S and never P, so it changes what the regulator's
        problem costs without changing how it should respond to a gap."""
        quiet, noisy = _problem(volatility=0.0), _problem(volatility=0.5)
        p_quiet, s_quiet = riccati_solution(quiet, 0.0)
        p_noisy, s_noisy = riccati_solution(noisy, 0.0)
        assert p_noisy == pytest.approx(p_quiet, rel=1e-9)
        assert s_noisy > s_quiet

    def test_costlier_enforcement_lowers_the_control_gain(self):
        """Higher r means the regulator leans on enforcement less for the
        same observed gap."""
        cheap = abs(optimal_control_lq(_problem(control_cost=0.5), 0.0, 1.0))
        dear = abs(optimal_control_lq(_problem(control_cost=5.0), 0.0, 1.0))
        assert dear < cheap

    def test_control_opposes_the_gap_and_is_linear_in_it(self):
        problem = _problem()
        assert optimal_control_lq(problem, 0.0, 2.0) < 0.0
        assert optimal_control_lq(problem, 0.0, -2.0) > 0.0
        assert optimal_control_lq(problem, 0.0, 2.0) == pytest.approx(
            2.0 * optimal_control_lq(problem, 0.0, 1.0)
        )

    def test_zero_gap_needs_no_enforcement(self):
        assert optimal_control_lq(_problem(), 0.0, 0.0) == pytest.approx(0.0)

    def test_time_outside_the_horizon_is_rejected(self):
        with pytest.raises(HjbError, match="outside"):
            riccati_solution(_problem(horizon=1.0), 2.0)


class TestFiniteDifferenceAgainstClosedForm:
    def test_recovers_the_value_function(self):
        problem = _problem()
        solution = solve_hjb(problem, grid_points=801)
        p, s = riccati_solution(problem, 0.0)

        for x in (-2.0, -1.0, 0.0, 0.5, 1.0, 2.0):
            assert solution.value_at(x) == pytest.approx(p * x * x + s, rel=2e-3, abs=2e-3)

    def test_recovers_the_optimal_policy_not_just_the_value(self):
        """Read off the computed surface's gradient, which is what a
        non-LQ solver would have to do."""
        problem = _problem()
        solution = solve_hjb(problem, grid_points=801)

        for x in (-2.0, -1.0, 0.5, 2.0):
            assert solution.control_at(x, problem) == pytest.approx(
                optimal_control_lq(problem, 0.0, x), rel=5e-3, abs=5e-3
            )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"drift": 0.4},
            {"terminal_cost": 0.0},
            {"state_cost": 3.0},
            {"control_cost": 4.0},
            {"horizon": 2.0},
        ],
        ids=["unstable-drift", "no-terminal-cost", "costly-gap", "costly-control", "long-horizon"],
    )
    def test_agrees_across_the_parameter_space(self, overrides):
        """One agreeing parameter set could be a fluke; the regimes here
        include an unstable drift (a > 0, so the gap runs away untended),
        a free terminal condition, and a doubled horizon."""
        problem = _problem(**overrides)
        assert _max_interior_error(problem, grid_points=801, window=1.5) < 5e-3


class TestConvergence:
    def test_error_falls_at_second_order(self):
        """Halving dx should quarter the error for central differences.
        A first-order rate here would mean a mis-centred stencil that a
        tolerance-based test would happily pass."""
        problem = _problem()
        errors = [_max_interior_error(problem, grid_points=n) for n in (201, 401, 801)]

        assert errors[0] > errors[1] > errors[2]
        for coarse, fine in pairwise(errors):
            ratio = coarse / fine
            assert 3.0 < ratio < 5.0, f"expected ~4x error reduction, got {ratio:.2f}"


class TestSolutionAccessors:
    def test_value_outside_the_grid_is_rejected(self):
        """Extrapolating a quadratic past the solved domain would return
        a confident wrong number."""
        solution = solve_hjb(_problem(), half_width=3.0, grid_points=101)
        with pytest.raises(HjbError, match="outside the solved grid"):
            solution.value_at(10.0)

    def test_control_outside_the_grid_is_rejected(self):
        problem = _problem()
        solution = solve_hjb(problem, half_width=3.0, grid_points=101)
        with pytest.raises(HjbError, match="outside the solved grid"):
            solution.control_at(-10.0, problem)

    def test_grid_covers_the_requested_width(self):
        solution = solve_hjb(_problem(), half_width=4.0, grid_points=101)
        assert solution.states[0] == pytest.approx(-4.0)
        assert solution.states[-1] == pytest.approx(4.0)
        assert solution.time_steps > 0

    def test_value_is_symmetric_about_zero(self):
        """Nothing in the problem distinguishes over- from
        under-compliance, so the value function must be even."""
        solution = solve_hjb(_problem(), grid_points=401)
        for x in (0.5, 1.0, 2.0):
            assert solution.value_at(x) == pytest.approx(solution.value_at(-x), rel=1e-6)

    def test_value_is_minimised_at_zero_gap(self):
        solution = solve_hjb(_problem(), grid_points=401)
        assert solution.value_at(0.0) < solution.value_at(1.0) < solution.value_at(2.0)


class TestIllPosedProblems:
    def test_free_enforcement_is_rejected(self):
        """r = 0 leaves the pointwise minimisation over u with no finite
        minimiser — the sweep would diverge silently instead."""
        with pytest.raises(HjbError, match="control_cost must be > 0"):
            _problem(control_cost=0.0)

    def test_negative_control_cost_is_rejected(self):
        with pytest.raises(HjbError, match="control_cost must be > 0"):
            _problem(control_cost=-1.0)

    def test_negative_state_cost_is_rejected(self):
        with pytest.raises(HjbError, match="non-negative"):
            _problem(state_cost=-1.0)

    def test_negative_volatility_is_rejected(self):
        with pytest.raises(HjbError, match="volatility"):
            _problem(volatility=-0.1)

    def test_non_positive_horizon_is_rejected(self):
        with pytest.raises(HjbError, match="horizon"):
            _problem(horizon=0.0)

    def test_a_deterministic_problem_is_refused_rather_than_returning_nan(self):
        """Pure advection is unconditionally unstable under this scheme,
        so it must refuse instead of sweeping to NaN. The closed form
        handles the deterministic case exactly."""
        with pytest.raises(HjbError, match="requires volatility > 0"):
            solve_hjb(_problem(volatility=0.0))

        exact_p, exact_s = riccati_solution(_problem(volatility=0.0), 0.0)
        assert exact_p > 0.0
        assert exact_s == pytest.approx(0.0)

    def test_unstable_cfl_is_rejected(self):
        with pytest.raises(HjbError, match="cfl"):
            solve_hjb(_problem(), cfl=0.9)

    def test_degenerate_grid_is_rejected(self):
        with pytest.raises(HjbError, match="grid_points"):
            solve_hjb(_problem(), grid_points=3)

    def test_non_positive_half_width_is_rejected(self):
        with pytest.raises(HjbError, match="half_width"):
            solve_hjb(_problem(), half_width=0.0)
