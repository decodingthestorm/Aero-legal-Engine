"""Property-based tests that convex_penalty is actually strictly convex,
and that calibrate_convexity_for_floor always meets its floor."""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from legal_engine.game_theory.models import ConvexPenaltyParams
from legal_engine.game_theory.penalty_optimizer import calibrate_convexity_for_floor, convex_penalty

_finite_floats = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)
_positive_floats = st.floats(
    min_value=1e-3, max_value=1e6, allow_nan=False, allow_infinity=False
)


@given(
    k=_positive_floats,
    x_limit=_finite_floats,
    x1=_finite_floats,
    x2=_finite_floats,
    t=st.floats(min_value=0.01, max_value=0.99, allow_nan=False),
)
def test_strict_convexity_midpoint_inequality(k, x_limit, x1, x2, t):
    """f(t*x1 + (1-t)*x2) <= t*f(x1) + (1-t)*f(x2), strict when x1 != x2."""
    assume(x1 != x2)
    params = ConvexPenaltyParams(k=k, x_limit=x_limit)

    midpoint = t * x1 + (1 - t) * x2
    lhs = convex_penalty(midpoint, params)
    rhs = t * convex_penalty(x1, params) + (1 - t) * convex_penalty(x2, params)

    assert lhs <= rhs + 1e-6


@given(k=_positive_floats, x_limit=_finite_floats, deviation=_positive_floats)
def test_penalty_increases_with_deviation_magnitude(k, x_limit, deviation):
    params = ConvexPenaltyParams(k=k, x_limit=x_limit)
    near = convex_penalty(x_limit + deviation, params)
    far = convex_penalty(x_limit + 2 * deviation, params)
    assert far >= near


@given(
    k=_positive_floats,
    x_limit=st.floats(min_value=-1e4, max_value=1e4, allow_nan=False),
    x_actual_offset=st.floats(min_value=1.0, max_value=1e4, allow_nan=False),
    floor=st.floats(min_value=0.0, max_value=1e6, allow_nan=False),
)
def test_calibration_always_meets_floor(k, x_limit, x_actual_offset, floor):
    params = ConvexPenaltyParams(k=k, x_limit=x_limit)
    x_actual = x_limit + x_actual_offset
    calibrated = calibrate_convexity_for_floor(x_actual, params, floor=floor)
    assert convex_penalty(x_actual, calibrated) >= floor - 1e-6
