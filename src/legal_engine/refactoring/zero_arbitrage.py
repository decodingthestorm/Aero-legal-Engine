"""Solves the cycle-basis system B * w = 0 to eliminate negative-weight loophole cycles.

For every cycle in a graph's fundamental cycle basis, the signed sum of edge
weights around it is a linear functional of the edge-weight vector. Any
cycle in the graph (not just basis cycles) is a linear combination of basis
cycles in the cycle space, so forcing every *basis* cycle's weighted sum to
zero forces every cycle's weighted sum to zero — that is the "zero
arbitrage" condition this module restores.

The basis is built by hand (BFS spanning forest + one fundamental cycle per
non-tree edge) rather than via ``nx.cycle_basis``, because that networkx
function operates on simple ``Graph`` objects: converting a ``DiGraph`` to
undirected via ``.to_undirected()`` silently merges a reciprocal pair of
directed edges (u->v and v->u) into a single undirected edge, which is
exactly the two-node loophole shape most statutory/tax cycles take (e.g. two
shell entities passing value back and forth). Building the spanning tree
over a ``MultiGraph`` instead preserves every directed edge as its own
column in B.

We solve for the minimum-norm correction vector w such that
``B @ (original_weights + w) == 0``, i.e. ``B @ w == -B @ original_weights``,
via least squares. Minimum-norm keeps the refactor as close as possible to
the original statutory boundary conditions instead of rewriting them
wholesale.
"""

from __future__ import annotations

from collections import deque

import networkx as nx
import numpy as np

from legal_engine.core.exceptions import UnbalancedCycleError

_TOLERANCE = 1e-6

Edge = tuple[str, str]


def build_cycle_basis_matrix(graph: nx.DiGraph) -> tuple[np.ndarray, list[Edge]]:
    edges: list[Edge] = list(graph.edges())
    edge_lookup: dict[int, Edge] = dict(enumerate(edges))

    multi = nx.MultiGraph()
    multi.add_nodes_from(graph.nodes())
    for idx, (u, v) in enumerate(edges):
        multi.add_edge(u, v, index=idx)

    # BFS spanning forest. parent[node] = (parent_node, edge_index, direction),
    # where direction is +1 if traversing parent_node -> node matches the
    # stored orientation of that directed edge, else -1.
    parent: dict[str, tuple[str, int, int]] = {}
    visited: set[str] = set()
    tree_edge_indices: set[int] = set()

    for start in multi.nodes():
        if start in visited:
            continue
        visited.add(start)
        queue: deque[str] = deque([start])
        while queue:
            node = queue.popleft()
            for neighbor in multi.neighbors(node):
                if neighbor in visited:
                    continue
                for _key, data in multi.get_edge_data(node, neighbor).items():
                    idx = data["index"]
                    if idx in tree_edge_indices:
                        continue
                    orig_u, orig_v = edge_lookup[idx]
                    direction = 1 if (node, neighbor) == (orig_u, orig_v) else -1
                    parent[neighbor] = (node, idx, direction)
                    tree_edge_indices.add(idx)
                    visited.add(neighbor)
                    queue.append(neighbor)
                    break

    def path_to_root_coeffs(node: str) -> dict[int, int]:
        coeffs: dict[int, int] = {}
        cur = node
        while cur in parent:
            p, idx, direction = parent[cur]
            coeffs[idx] = coeffs.get(idx, 0) - direction
            cur = p
        return coeffs

    rows: list[dict[int, int]] = []
    for idx, (u, v) in enumerate(edges):
        if idx in tree_edge_indices:
            continue
        row = dict(path_to_root_coeffs(u))
        for k, val in path_to_root_coeffs(v).items():
            row[k] = row.get(k, 0) - val
        row[idx] = row.get(idx, 0) - 1
        rows.append(row)

    B = np.zeros((len(rows), len(edges)))
    for r, row in enumerate(rows):
        for col, coeff in row.items():
            B[r, col] = coeff

    return B, edges


def solve_zero_arbitrage(graph: nx.DiGraph) -> dict[Edge, float]:
    """Return the minimum-norm per-edge weight correction that zeroes every basis cycle."""
    B, edges = build_cycle_basis_matrix(graph)

    if B.shape[0] == 0:
        return {edge: 0.0 for edge in edges}

    original_weights = np.array([graph[u][v]["weight"] for u, v in edges])
    target = -(B @ original_weights)

    correction, _residuals, _rank, _singular_values = np.linalg.lstsq(B, target, rcond=None)

    if not np.allclose(B @ correction, target, atol=_TOLERANCE):
        raise UnbalancedCycleError(
            "No correction vector satisfies B @ w = -B @ original_weights within tolerance; "
            "the cycle basis system is inconsistent"
        )

    return {edges[i]: float(correction[i]) for i in range(len(edges))}


def apply_correction(graph: nx.DiGraph, correction: dict[Edge, float]) -> nx.DiGraph:
    """Return a new graph with corrections added to each edge's weight."""
    balanced = graph.copy()
    for (u, v), delta in correction.items():
        balanced[u][v]["weight"] += delta
    return balanced
