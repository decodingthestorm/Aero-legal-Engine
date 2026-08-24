"""Dependency injection for the API layer.

Every route depends on the Protocol interfaces (GraphService, VectorIndex,
Embedder, StatuteRepository) rather than a concrete class, so which backend
main.py's lifespan actually constructs is a settings change
(knowledge_graph/factory.py, persistence/factory.py), not a route change;
and ``require_auth`` below is a real, working (if deliberately simple) JWT
check, off by default via settings.api_auth_enabled.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from legal_engine.api.security import InvalidTokenError, verify_token
from legal_engine.core.config import settings
from legal_engine.formal_logic.solver_pool import SolverPool
from legal_engine.ingestion.rate_limiter import PoliteFetcher
from legal_engine.knowledge_graph.embeddings import Embedder
from legal_engine.knowledge_graph.graph_service import GraphService
from legal_engine.knowledge_graph.vector_service import VectorIndex
from legal_engine.persistence.repository import StatuteRepository


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


def get_statute_repository(request: Request) -> StatuteRepository:
    return request.app.state.statute_repository


async def require_auth(request: Request) -> str | None:
    """No-ops (returns None) when settings.api_auth_enabled is False — the
    default, and what every other test in this suite runs against. When
    enabled, requires a valid ``Authorization: Bearer <token>`` header
    (issued by POST /auth/token) and returns the token's subject."""
    if not settings.api_auth_enabled:
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        return verify_token(auth_header.removeprefix("Bearer "))
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


GraphServiceDep = Annotated[GraphService, Depends(get_graph_service)]
VectorIndexDep = Annotated[VectorIndex, Depends(get_vector_index)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
SolverPoolDep = Annotated[SolverPool, Depends(get_solver_pool)]
FetcherDep = Annotated[PoliteFetcher, Depends(get_fetcher)]
StatuteRepositoryDep = Annotated[StatuteRepository, Depends(get_statute_repository)]
