"""Exercises refactoring/sparse_optimizer.py's L1-sparse correction for
real against cvxpy — it imports successfully in this environment (see the
module's own docstring for the one transient failure it hit on first
import), unlike sentence-transformers/torch, so these aren't gated behind
a "can't verify locally" skip.
"""

from __future__ import annotations

import pytest

from legal_engine.core.exceptions import UnbalancedCycleError
from legal_engine.refactoring.dependency_graph import DependencyGraphBuilder
from legal_engine.refactoring.sparse_optimizer import solve_sparse_correction
from legal_engine.refactoring.zero_arbitrage import apply_correction, solve_zero_arbitrage

_TOLERANCE = 1e-3


def _reconvergent_diamond_graph():
    """Two triangular cycles (a->b->d->a and a->c->d->a) sharing only the
    chord edge d->a. Deliberately not the single-2-edge-cycle shape
    test_refactoring.py's _loophole_graph() uses: with only one equation
    tying two same-signed unknowns together, L1 and L2 minimization are
    degenerate/indistinguishable there (any split has the same L1 norm).
    This shape has two equations (one basis cycle per chord) sharing one
    variable, which is where L1 and L2 actually diverge: L1 can zero out
    every edge except the one both cycles have in common, L2 cannot."""
    return (
        DependencyGraphBuilder()
        .add_dependency("a", "b", weight=2.0)
        .add_dependency("b", "d", weight=2.0)
        .add_dependency("a", "c", weight=2.0)
        .add_dependency("c", "d", weight=2.0)
        .add_dependency("d", "a", weight=-10.0)
        .build()
    )


def _cycle_sum(graph, nodes: tuple[str, ...]) -> float:
    total = 0.0
    n = len(nodes)
    for i in range(n):
        u, v = nodes[i], nodes[(i + 1) % n]
        total += graph[u][v]["weight"]
    return total


class TestSparseCorrectionZeroesEveryCycle:
    def test_reconvergent_diamond_both_cycles_zero_out(self):
        graph = _reconvergent_diamond_graph()
        correction = solve_sparse_correction(graph)
        balanced = apply_correction(graph, correction)

        assert _cycle_sum(balanced, ("a", "b", "d")) == pytest.approx(0.0, abs=_TOLERANCE)
        assert _cycle_sum(balanced, ("a", "c", "d")) == pytest.approx(0.0, abs=_TOLERANCE)

    def test_graph_without_cycles_returns_zero_correction(self):
        graph = (
            DependencyGraphBuilder()
            .add_dependency("statute_a", "statute_b", weight=5.0)
            .add_dependency("statute_b", "statute_c", weight=2.0)
            .build()
        )
        correction = solve_sparse_correction(graph)
        assert all(v == 0.0 for v in correction.values())


class TestSparsityVsMinimumNorm:
    """The actual point of this module, verified concretely rather than
    just asserted: L1 minimization changes as few edges as possible, L2
    (solve_zero_arbitrage) spreads the change across every edge."""

    def test_l1_touches_only_the_shared_chord_edge(self):
        graph = _reconvergent_diamond_graph()
        correction = solve_sparse_correction(graph)

        untouched_edges = [("a", "b"), ("b", "d"), ("a", "c"), ("c", "d")]
        for edge in untouched_edges:
            assert correction[edge] == pytest.approx(0.0, abs=_TOLERANCE)
        assert correction[("d", "a")] == pytest.approx(6.0, abs=_TOLERANCE)

    def test_l2_spreads_the_same_correction_across_every_edge(self):
        """Same graph, solve_zero_arbitrage's existing minimum-norm
        solver: nothing comes out to zero — this is the "dense edit" the
        module docstring contrasts sparse correction against."""
        graph = _reconvergent_diamond_graph()
        correction = solve_zero_arbitrage(graph)

        assert all(abs(v) > 1.0 for v in correction.values())
        assert correction[("d", "a")] == pytest.approx(3.0, abs=_TOLERANCE)

    def test_l1_correction_changes_fewer_edges_than_l2(self):
        graph = _reconvergent_diamond_graph()
        l1_nonzero = sum(1 for v in solve_sparse_correction(graph).values() if abs(v) > 1e-3)
        l2_nonzero = sum(1 for v in solve_zero_arbitrage(graph).values() if abs(v) > 1e-3)

        assert l1_nonzero < l2_nonzero
        assert l1_nonzero == 1


class TestMaxDeltaBound:
    def test_feasible_bound_forces_spreading_beyond_the_single_edge(self):
        """max_delta=4.0 rules out the unbounded solution (a single +6.0
        edit), forcing the solver to spread the correction across enough
        edges to stay within the per-edge cap while still zeroing both
        cycles."""
        graph = _reconvergent_diamond_graph()
        correction = solve_sparse_correction(graph, max_delta=4.0)
        balanced = apply_correction(graph, correction)

        assert max(abs(v) for v in correction.values()) <= 4.0 + _TOLERANCE
        assert _cycle_sum(balanced, ("a", "b", "d")) == pytest.approx(0.0, abs=_TOLERANCE)
        assert _cycle_sum(balanced, ("a", "c", "d")) == pytest.approx(0.0, abs=_TOLERANCE)

    def test_infeasible_bound_raises_unbalanced_cycle_error(self):
        graph = _reconvergent_diamond_graph()
        with pytest.raises(UnbalancedCycleError, match="max_delta"):
            solve_sparse_correction(graph, max_delta=0.5)


class TestMissingDependency:
    def test_fails_closed_with_install_hint_when_cvxpy_unavailable(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "cvxpy":
                raise ImportError("No module named 'cvxpy'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked_import)

        graph = _reconvergent_diamond_graph()
        with pytest.raises(ImportError, match="pip install -e '.\\[sparse-opt\\]'"):
            solve_sparse_correction(graph)
