"""Arbitrage loop detection endpoints.

Exposes refactoring.cycle_detector and refactoring.zero_arbitrage: submit a
dependency graph's edges, get back negative-weight loophole cycles and the
minimum-norm correction that zeroes them out. Also exposes
refactoring.sparse_optimizer's L1-sparse alternative correction as a
separate endpoint (different optional dependency, different response
shape — kept independently failable rather than folded into
/detect-loopholes's response).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from legal_engine.refactoring.cycle_detector import find_negative_weight_cycles
from legal_engine.refactoring.dependency_graph import DependencyGraphBuilder
from legal_engine.refactoring.sparse_optimizer import solve_sparse_correction
from legal_engine.refactoring.zero_arbitrage import solve_zero_arbitrage

router = APIRouter()


class EdgeSchema(BaseModel):
    source: str
    target: str
    weight: float


class DetectLoopholesRequest(BaseModel):
    edges: list[EdgeSchema]


class LoopholeSchema(BaseModel):
    nodes: list[str]
    total_weight: float


class DetectLoopholesResponse(BaseModel):
    loopholes: list[LoopholeSchema]
    corrections: dict[str, float]


@router.post("/detect-loopholes", response_model=DetectLoopholesResponse)
async def detect_loopholes(request: DetectLoopholesRequest) -> DetectLoopholesResponse:
    builder = DependencyGraphBuilder()
    for edge in request.edges:
        builder.add_dependency(edge.source, edge.target, edge.weight)
    graph = builder.build()

    loopholes = find_negative_weight_cycles(graph)
    corrections = solve_zero_arbitrage(graph)

    return DetectLoopholesResponse(
        loopholes=[LoopholeSchema(nodes=list(lh.nodes), total_weight=lh.total_weight) for lh in loopholes],
        corrections={f"{u}->{v}": weight for (u, v), weight in corrections.items()},
    )


class SparsePatchRequest(BaseModel):
    edges: list[EdgeSchema]
    # Policy-defined cap on any single edge's amendment size — see
    # refactoring/sparse_optimizer.py's solve_sparse_correction docstring.
    max_delta: float | None = None


class SparsePatchResponse(BaseModel):
    corrections: dict[str, float]
    edges_changed: int


@router.post("/sparse-patch", response_model=SparsePatchResponse)
async def sparse_patch(request: SparsePatchRequest) -> SparsePatchResponse:
    builder = DependencyGraphBuilder()
    for edge in request.edges:
        builder.add_dependency(edge.source, edge.target, edge.weight)
    graph = builder.build()

    try:
        corrections = solve_sparse_correction(graph, max_delta=request.max_delta)
    except ImportError as exc:
        # cvxpy (the `sparse-opt` install extra) isn't installed on this
        # deployment — a capability gap, not a bad request, so 503 rather
        # than 400 (UnbalancedCycleError, the "no feasible patch exists"
        # case, is a LegalEngineError and already maps to 400 via
        # api/middleware.py without any handling needed here).
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    # The solver's own numerical noise floor on an edge it drove to zero is
    # around 1e-8-1e-9 (see tests/unit/test_sparse_optimizer.py) — well
    # under this threshold, so it doesn't get counted as "changed."
    edges_changed = sum(1 for weight in corrections.values() if abs(weight) > 1e-4)
    return SparsePatchResponse(
        corrections={f"{u}->{v}": weight for (u, v), weight in corrections.items()},
        edges_changed=edges_changed,
    )
