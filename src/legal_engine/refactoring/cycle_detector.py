"""Finds negative-weight circular loophole cycles in the statutory/tax dependency graph.

Two-stage approach:

1. Tarjan's Strongly Connected Components (nx.strongly_connected_components,
   which is a Tarjan-style linear-time SCC algorithm) narrows the search to
   the subgraphs where cycles can even exist — no point running cycle
   enumeration over the whole graph when most of it is a DAG.
2. Johnson's algorithm (nx.simple_cycles, Johnson-style for directed graphs)
   enumerates every simple cycle within each non-trivial SCC. Each cycle's
   total weight is summed; a negative sum means the loophole nets positive
   value to whoever routes value flow around it.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx


@dataclass
class LoopholeCycle:
    nodes: tuple[str, ...]
    total_weight: float


def find_negative_weight_cycles(graph: nx.DiGraph) -> list[LoopholeCycle]:
    loopholes: list[LoopholeCycle] = []

    for scc in nx.strongly_connected_components(graph):
        if len(scc) < 2 and not graph.has_edge(next(iter(scc)), next(iter(scc))):
            continue  # singleton with no self-loop: cannot contain a cycle

        subgraph = graph.subgraph(scc)
        for cycle_nodes in nx.simple_cycles(subgraph):
            total_weight = _cycle_weight(subgraph, cycle_nodes)
            if total_weight < 0:
                loopholes.append(LoopholeCycle(nodes=tuple(cycle_nodes), total_weight=total_weight))

    return loopholes


def _cycle_weight(graph: nx.DiGraph, cycle_nodes: list[str]) -> float:
    total = 0.0
    n = len(cycle_nodes)
    for i in range(n):
        u, v = cycle_nodes[i], cycle_nodes[(i + 1) % n]
        total += graph[u][v]["weight"]
    return total
