"""Dependency injection for the API layer.

There is no Postgres/Redis-backed persistence or JWT auth wired up yet
(despite those settings existing in core/config.py) — this is an
in-process demo API, not a production gateway. What *is* real: every route
depends on the Protocol interfaces (GraphService, VectorIndex, Embedder —
see knowledge_graph/) rather than a concrete class, so swapping the
in-memory defaults for Neo4jGraphService/QdrantVectorIndex/
SentenceTransformerEmbedder in production is a one-line change in
main.py's lifespan, not a change to any route.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from legal_engine.formal_logic.solver_pool import SolverPool
from legal_engine.ingestion.rate_limiter import PoliteFetcher
from legal_engine.knowledge_graph.embeddings import Embedder
from legal_engine.knowledge_graph.graph_service import GraphService
from legal_engine.knowledge_graph.vector_service import VectorIndex


def get_graph_service(request: Request) -> GraphService:
    return request.app.state.graph_service


def get_vector_index(request: Request) -> VectorIndex:
    return request.app.state.vector_index


def get_embedder(request: Request) -> Embedder:
    return request.app.state.embedder


def get_solver_pool(request: Request) -> SolverPool:
    return request.app.state.solver_pool


def get_fetcher(request: Request) -> PoliteFetcher:
    return request.app.state.fetcher


GraphServiceDep = Annotated[GraphService, Depends(get_graph_service)]
VectorIndexDep = Annotated[VectorIndex, Depends(get_vector_index)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
SolverPoolDep = Annotated[SolverPool, Depends(get_solver_pool)]
FetcherDep = Annotated[PoliteFetcher, Depends(get_fetcher)]
