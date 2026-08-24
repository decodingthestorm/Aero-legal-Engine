"""Continuous-time regulatory control: a Hamilton-Jacobi-Bellman solver
for the regulator's problem, with a closed-form solution to check it
against.

## The problem

A regulator watches a compliance gap `x` — how far a regulated entity sits
from where the statute wants it — and chooses an enforcement intensity `u`
(audit rate, penalty severity, disclosure burden). The gap evolves as

    dx = (a·x + b·u) dt + σ dW

and the regulator minimises

    E[ ∫₀ᵀ (q·x² + r·u²) dt + q_T·x_T² ]

`q` prices the harm of non-compliance, `r` prices enforcement — auditing
is not free, and a regulator that ignores its own costs will over-enforce.
`a` is how the gap drifts unattended (negative for an entity that drifts
back toward compliance on its own), `σ` is the shock the regulator cannot
see coming.

The value function solves the HJB equation

    ∂V/∂t + min_u { (a·x + b·u)·V_x + ½σ²·V_xx + q·x² + r·u² } = 0

with `V(T,x) = q_T·x²`. Minimising over `u` pointwise gives the feedback
law `u* = -(b/2r)·V_x` in closed form, which is what makes a
finite-difference sweep tractable: there is no inner optimisation, just a
substitution at each grid point.

## Why there is both a solver and a closed form

An earlier specification mandated linear-quadratic structure *and* a
"unique viscosity solution" computed by implicit finite differences.
Those pull in opposite directions. Viscosity solutions are the machinery
for when the value function is *not* smooth — non-LQ dynamics, state
constraints, degenerate diffusion. If the problem really is LQ, `V` is
smooth and quadratic, the HJB collapses to a Riccati ODE, and you can
simply write the answer down.

The resolution is not to pick one but to see the relationship: the finite
difference sweep is the general tool, and the LQ closed form is its
*test oracle*. `solve_hjb` knows nothing about the quadratic structure —
it discretises the equation as written — and `riccati_solution` computes
the exact answer independently. `tests/unit/test_hjb.py` checks they
agree, and checks the error falls at the second-order rate central
differences should give. Numerical agreement to a fixed tolerance can be
luck; the convergence *order* being right is much harder to fake.

## Deliberately out of scope

**No jump term.** The source specification had a compensated Poisson
random measure alongside the diffusion. That turns the HJB into a partial
*integro*-differential equation whose non-local term needs quadrature at
every grid point, and — more to the point — there would be no closed form
left to validate against. One dimension, one Brownian driver.

**One state dimension.** The grid is a line, so this does not model
several interacting regulated entities.

**Not a Stackelberg game.** The specification described a leader-follower
equilibrium and asserted it reduces to a single control problem "via exact
first-order potential game conditions." Stackelberg games do not
generically admit a potential-game reduction, and the structure that
would justify one was never established. What is solved here is the
single-agent control problem honestly, not a two-player equilibrium
relabelled.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp

from legal_engine.core.exceptions import LegalEngineError


class HjbError(LegalEngineError):
    """The problem is ill-posed, or the solver was asked for something
    outside the grid it computed."""


@dataclass(frozen=True)
class LqRegulatorProblem:
    """``control_cost`` must be strictly positive. At zero, enforcement is
    free, the pointwise minimisation over ``u`` has no finite minimiser,
    and the value function is unbounded below — a degenerate problem that
    would otherwise show up as a silently diverging sweep rather than an
    error."""

    drift: float
    control_gain: float
    volatility: float
    state_cost: float
    control_cost: float
    terminal_cost: float
    horizon: float

    def __post_init__(self) -> None:
        if self.control_cost <= 0.0:
            raise HjbError(
                f"control_cost must be > 0 (got {self.control_cost}); with costless enforcement "
                "the value function is unbounded below"
            )
        if self.state_cost < 0.0 or self.terminal_cost < 0.0:
            raise HjbError("state_cost and terminal_cost must be non-negative")
        if self.volatility < 0.0:
            raise HjbError("volatility must be non-negative")
        if self.horizon <= 0.0:
            raise HjbError(f"horizon must be > 0 (got {self.horizon})")


def riccati_solution(problem: LqRegulatorProblem, time: float) -> tuple[float, float]:
    """Exact ``(P, S)`` at ``time``, where ``V(t, x) = P(t)·x² + S(t)``.

    Substituting that ansatz into the HJB and matching powers of ``x``
    gives two backward ODEs, integrated here in ``τ = T - t``:

        dP/dτ = 2a·P - b²·P²/r + q,   P(0) = q_T
        dS/dτ = σ²·P,                 S(0) = 0

    ``S`` collects the cost of the noise the regulator cannot control: it
    is zero when ``σ`` is, and never affects the optimal policy, only the
    value.
    """
    if not 0.0 <= time <= problem.horizon:
        raise HjbError(f"time {time} is outside [0, {problem.horizon}]")

    a, b = problem.drift, problem.control_gain
    q, r, sigma = problem.state_cost, problem.control_cost, problem.volatility

    def backward(_tau: float, state: np.ndarray) -> list[float]:
        p, _s = state
        return [2.0 * a * p - b * b * p * p / r + q, sigma * sigma * p]

    tau = problem.horizon - time
    if tau == 0.0:
        return problem.terminal_cost, 0.0

    solution = solve_ivp(
        backward,
        (0.0, tau),
        [problem.terminal_cost, 0.0],
        rtol=1e-10,
        atol=1e-12,
        dense_output=True,
    )
    if not solution.success:
        raise HjbError(f"Riccati integration failed: {solution.message}")
    p, s = solution.sol(tau)
    return float(p), float(s)


def optimal_control_lq(problem: LqRegulatorProblem, time: float, state: float) -> float:
    """The exact feedback law ``u*(t, x) = -(b/r)·P(t)·x``. Linear in the
    gap and independent of ``σ``: noise changes what the regulator's
    problem *costs*, not how it should respond to a given gap."""
    p, _ = riccati_solution(problem, time)
    return -(problem.control_gain / problem.control_cost) * p * state


@dataclass(frozen=True)
class HjbSolution:
    """``values[i]`` is ``V(0, states[i])`` — the sweep runs backward from
    the terminal condition to ``t = 0`` and only the final slice is
    retained, since that is the one a regulator acts on today."""

    states: np.ndarray
    values: np.ndarray
    grid_spacing: float
    time_steps: int

    def value_at(self, state: float) -> float:
        self._require_in_grid(state)
        return float(np.interp(state, self.states, self.values))

    def control_at(self, state: float, problem: LqRegulatorProblem) -> float:
        """``u* = -(b/2r)·V_x``, read off the computed surface rather than
        from the closed form — this is what a solver for a *non*-LQ
        problem would return, and comparing it against
        ``optimal_control_lq`` is what shows the sweep recovered the
        policy and not merely the value."""
        self._require_in_grid(state)
        gradient = np.gradient(self.values, self.grid_spacing)
        slope = float(np.interp(state, self.states, gradient))
        return -(problem.control_gain / (2.0 * problem.control_cost)) * slope

    def _require_in_grid(self, state: float) -> None:
        low, high = float(self.states[0]), float(self.states[-1])
        if not low <= state <= high:
            raise HjbError(f"state {state} is outside the solved grid [{low}, {high}]")


def solve_hjb(
    problem: LqRegulatorProblem,
    half_width: float = 6.0,
    grid_points: int = 401,
    cfl: float = 0.4,
) -> HjbSolution:
    """Explicit backward finite-difference sweep of the HJB equation.

    The scheme is explicit, so the time step is bounded by stability
    rather than chosen: ``dt ≤ cfl·dx²/σ²``. An implicit scheme would lift
    that bound, but at this size the sweep takes milliseconds and an
    explicit one is far easier to read against the equation it
    discretises — which matters more here, since being *checkable* is the
    whole reason this exists alongside a closed form.

    Boundaries extrapolate ``V_xx`` from the adjacent interior node rather
    than imposing the known quadratic growth. Pinning the analytic value
    at the edges would make the validation partly circular — the solver
    would be handed a piece of the answer it is supposed to reproduce. The
    cost is that error is largest near the edges, so ``half_width`` should
    leave the region of interest well inside the grid.
    """
    if grid_points < 5:
        raise HjbError(f"grid_points must be at least 5 (got {grid_points})")
    if half_width <= 0.0:
        raise HjbError(f"half_width must be > 0 (got {half_width})")
    if not 0.0 < cfl <= 0.5:
        raise HjbError(f"cfl must be in (0, 0.5] for stability (got {cfl})")
    if problem.volatility <= 0.0:
        # Not a tuning problem. With no diffusion the HJB is pure
        # advection, and forward-Euler with central differences is
        # *unconditionally* unstable for advection — no time step makes
        # it converge, and the sweep silently returns NaN rather than a
        # wrong-but-finite answer. Upwinding the drift term would fix the
        # stability at the cost of dropping the scheme to first order,
        # which would also cost the convergence-rate check that is this
        # solver's strongest validation. The deterministic problem has an
        # exact solution anyway.
        raise HjbError(
            "solve_hjb requires volatility > 0: with no diffusion this scheme is "
            "unconditionally unstable. Use riccati_solution/optimal_control_lq, which "
            "solve the deterministic case exactly."
        )

    a, b = problem.drift, problem.control_gain
    q, r, sigma = problem.state_cost, problem.control_cost, problem.volatility

    states = np.linspace(-half_width, half_width, grid_points)
    dx = float(states[1] - states[0])

    steps = int(np.ceil(problem.horizon / (cfl * dx * dx / (sigma * sigma)))) + 1
    dt = problem.horizon / steps

    values = problem.terminal_cost * states**2

    for _ in range(steps):
        slope = np.gradient(values, dx)
        slope[0] = (values[1] - values[0]) / dx
        slope[-1] = (values[-1] - values[-2]) / dx

        curvature = np.empty_like(values)
        curvature[1:-1] = (values[2:] - 2.0 * values[1:-1] + values[:-2]) / (dx * dx)
        curvature[0], curvature[-1] = curvature[1], curvature[-2]

        control = -(b / (2.0 * r)) * slope
        values = values + dt * (
            (a * states + b * control) * slope
            + 0.5 * sigma * sigma * curvature
            + q * states**2
            + r * control**2
        )

    return HjbSolution(states=states, values=values, grid_spacing=dx, time_steps=steps)
