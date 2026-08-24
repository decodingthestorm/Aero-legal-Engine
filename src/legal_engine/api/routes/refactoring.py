"""Arbitrage loop detection endpoints.

Exposes refactoring.cycle_detector and refactoring.zero_arbitrage: submit a
dependency graph's edges, get back negative-weight loophole cycles and the
minimum-norm correction that zeroes them out.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from legal_engine.refactoring.cycle_detector import find_negative_weight_cycles
from legal_engine.refactoring.dependency_graph import DependencyGraphBuilder
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
