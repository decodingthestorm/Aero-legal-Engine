"""Builds the directed, weighted statutory/tax dependency graph.

An edge (u -> v, weight=w) means "obligation/benefit node u flows w units of
value into node v" — e.g. a deduction, credit, exemption, or transfer
pricing rule. A negative-weight cycle in this graph is a loophole: value can
be round-tripped through it for a net gain (see cycle_detector.py).
"""

from __future__ import annotations

from typing import Any

import networkx as nx


class DependencyGraphBuilder:
    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()

    def add_node(self, node_id: str, **attrs: Any) -> DependencyGraphBuilder:
        self._graph.add_node(node_id, **attrs)
        return self

    def add_dependency(
        self, source: str, target: str, weight: float, **attrs: Any
    ) -> DependencyGraphBuilder:
        self._graph.add_edge(source, target, weight=weight, **attrs)
        return self

    def build(self) -> nx.DiGraph:
        return self._graph
