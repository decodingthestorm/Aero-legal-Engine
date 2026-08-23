import pytest

from legal_engine.refactoring.cycle_detector import find_negative_weight_cycles
from legal_engine.refactoring.dependency_graph import DependencyGraphBuilder
from legal_engine.refactoring.zero_arbitrage import apply_correction, solve_zero_arbitrage


def _loophole_graph():
    return (
        DependencyGraphBuilder()
        .add_dependency("shell_co_a", "shell_co_b", weight=-3.0)
        .add_dependency("shell_co_b", "shell_co_a", weight=1.0)
        .build()
    )


def _dag_graph():
    return (
        DependencyGraphBuilder()
        .add_dependency("statute_a", "statute_b", weight=5.0)
        .add_dependency("statute_b", "statute_c", weight=2.0)
        .build()
    )


class TestCycleDetector:
    def test_finds_negative_weight_cycle(self):
        graph = _loophole_graph()
        loopholes = find_negative_weight_cycles(graph)
        assert len(loopholes) == 1
        assert loopholes[0].total_weight == pytest.approx(-2.0)
        assert set(loopholes[0].nodes) == {"shell_co_a", "shell_co_b"}

    def test_dag_has_no_cycles(self):
        graph = _dag_graph()
        assert find_negative_weight_cycles(graph) == []

    def test_positive_cycle_is_not_flagged(self):
        graph = (
            DependencyGraphBuilder()
            .add_dependency("a", "b", weight=3.0)
            .add_dependency("b", "a", weight=5.0)
            .build()
        )
        assert find_negative_weight_cycles(graph) == []


class TestZeroArbitrage:
    def test_solve_zeroes_the_loophole_cycle(self):
        graph = _loophole_graph()
        correction = solve_zero_arbitrage(graph)
        balanced = apply_correction(graph, correction)

        cycle_sum = balanced["shell_co_a"]["shell_co_b"]["weight"] + balanced["shell_co_b"]["shell_co_a"]["weight"]
        assert cycle_sum == pytest.approx(0.0, abs=1e-6)

    def test_graph_without_cycles_returns_zero_correction(self):
        graph = _dag_graph()
        correction = solve_zero_arbitrage(graph)
        assert all(v == 0.0 for v in correction.values())

    def test_minimum_norm_correction_is_symmetric_for_symmetric_loophole(self):
        graph = _loophole_graph()
        correction = solve_zero_arbitrage(graph)
        a_to_b = correction[("shell_co_a", "shell_co_b")]
        b_to_a = correction[("shell_co_b", "shell_co_a")]
        # Minimum-norm least-squares solution splits the -2 deficit evenly.
        assert a_to_b == pytest.approx(1.0, abs=1e-6)
        assert b_to_a == pytest.approx(1.0, abs=1e-6)
