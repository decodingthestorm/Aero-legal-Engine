"""L1-sparse statutory patch generation — a "surgical" alternative to
zero_arbitrage.py's minimum-L2-norm loophole correction.

``solve_zero_arbitrage`` finds the minimum-*L2*-norm correction vector w
such that ``B @ (original_weights + w) == 0`` — every basis cycle's
weighted sum comes out to zero. Minimum-L2-norm distributes the fix across
every edge a little bit (see that module's own docstring: "keeps the
refactor as close as possible to the original... boundary conditions").
That is the right objective for a numerical rebalancing, but the wrong one
for something meant to become an actual legislative amendment: a regulator
proposing "clause 1: +0.12%, clause 2: -0.08%, clause 3: +0.45%, ..."
across every provision in the graph is not a bill anyone can pass — a
patch that touches one or two clauses is.

This module minimizes the *L1* norm of the correction instead, subject to
the identical constraint. This is the standard sparsity-inducing
reformulation (Lasso / compressed sensing): L1 minimization drives most of
a solution's components to exactly zero rather than spreading a small
residual across every one, so among the (generally infinite) family of
correction vectors that all zero every basis cycle, it selects one that
changes as few edges as possible.

Minimizing sum(|w_j|) subject to a linear equality (and an optional box
bound |w_j| <= max_delta) is itself a linear program — no need for a
nonlinear or commercial solver. This uses cvxpy purely as a modeling layer
over its bundled open-source LP solvers (Clarabel/OSQP/ECOS, whichever it
picks by default), not MOSEK, which needs a paid license this project has
no access to.

cvxpy is a lazy-imported optional dependency (the ``sparse-opt`` install
extra), matching every other "real backend" in this codebase
(knowledge_graph's Neo4j/Qdrant/sentence-transformers, ingestion's
Tesseract OCR) — genuinely exercised and passing in this environment
(unlike those), not just asserted to fail closed with an install hint. It
did fail once here on its very first import attempt, the same class of
issue ``knowledge_graph/embeddings.py`` documents for sentence-
transformers/torch: ``ImportError: DLL load failed while importing
_decomp_interpolative: An Application Control policy has blocked this
file`` — a native DLL several layers into cvxpy's import chain (inside
scipy, pulled in transitively by one of cvxpy's atom modules). That
turned out to be a one-time first-access scan, not a standing block —
every import since has succeeded. The lazy import below still guards with
a broad ``except Exception`` rather than just ``except ImportError``,
consistent with the sentence-transformers/torch precedent, since a
transient failure like this one is exactly the shape of thing worth
degrading gracefully from rather than crashing the whole request on.
"""

from __future__ import annotations

import networkx as nx
import numpy as np

from legal_engine.core.exceptions import UnbalancedCycleError
from legal_engine.refactoring.zero_arbitrage import Edge, build_cycle_basis_matrix

_TOLERANCE = 1e-6


def solve_sparse_correction(graph: nx.DiGraph, max_delta: float | None = None) -> dict[Edge, float]:
    """Returns the minimum-L1-norm correction vector w such that
    ``B @ (original_weights + w) == 0`` — the sparsest (fewest-edges-
    changed) correction that still zeroes every basis cycle, in contrast
    to ``solve_zero_arbitrage``'s minimum-L2-norm (spreads-the-change-
    everywhere) correction.

    ``max_delta``, if given, bounds every ``|w_j| <= max_delta`` — a
    policy-defined limit on how large a single amendment's rate change is
    allowed to be. A single symmetric bound rather than separate
    ``w_min``/``w_max`` per edge, since there's no per-edge policy
    asymmetry (e.g. "this provision may only be raised, never lowered")
    to express yet — widen this to a per-edge bound if that need shows up.

    Raises ImportError (with install instructions) if cvxpy isn't
    installed or fails to import for any reason (see the module
    docstring). Raises UnbalancedCycleError if the constraint system has
    no feasible solution — either genuinely inconsistent (same case
    ``solve_zero_arbitrage`` raises for), or feasible without bounds but
    infeasible under the given ``max_delta``.
    """
    try:
        import cvxpy as cp
    except Exception as exc:
        raise ImportError(
            "solve_sparse_correction needs cvxpy, which failed to import "
            f"({type(exc).__name__}: {exc}). Install it with "
            "`pip install -e '.[sparse-opt]'`, or if it's already installed, "
            "this environment may be blocking one of its native dependencies."
        ) from exc

    B, edges = build_cycle_basis_matrix(graph)

    if B.shape[0] == 0:
        return {edge: 0.0 for edge in edges}

    original_weights = np.array([graph[u][v]["weight"] for u, v in edges])
    target = -(B @ original_weights)

    w = cp.Variable(len(edges))
    constraints = [B @ w == target]
    if max_delta is not None:
        constraints.append(cp.abs(w) <= max_delta)

    problem = cp.Problem(cp.Minimize(cp.norm1(w)), constraints)
    problem.solve()

    if w.value is None or problem.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
        reason = "outside the given max_delta bounds" if max_delta is not None else "inconsistent"
        raise UnbalancedCycleError(
            "No sparse correction vector satisfies B @ w = -B @ original_weights "
            f"(solver status: {problem.status!r}); the cycle basis system is {reason}"
        )

    correction = np.asarray(w.value).flatten()
    if not np.allclose(B @ correction, target, atol=_TOLERANCE):
        raise UnbalancedCycleError(
            "Solver reported success but the returned correction does not actually "
            "satisfy B @ w = -B @ original_weights within tolerance"
        )

    return {edges[i]: float(correction[i]) for i in range(len(edges))}
