"""FastAPI application entry point.

Constructs the shared in-process state (graph, vector index, embedder,
solver pool, HTTP fetcher) once at startup via ``lifespan`` and tears down
the fetcher's connection pool on shutdown. Which concrete class backs the
graph/vector/embedder Protocols is decided by
knowledge_graph.factory (itself driven by core.config.settings) — swapping
in Neo4j/Qdrant/sentence-transformers for production is a settings change,
not a code change here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from legal_engine.api.dependencies import require_auth
from legal_engine.api.middleware import add_middleware
from legal_engine.api.routes import auth, graph, ingestion, refactoring, simulation, verification
from legal_engine.core.config import settings
from legal_engine.core.logging import configure_logging, get_logger
from legal_engine.formal_logic.solver_pool import SolverPool
from legal_engine.ingestion.rate_limiter import PoliteFetcher
from legal_engine.knowledge_graph.factory import (
    build_embedder,
    build_graph_service,
    build_vector_index,
)
from legal_engine.persistence.factory import build_statute_repository
from legal_engine.persistence.hydration import hydrate_indexes

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    app.state.graph_service = build_graph_service()
    app.state.vector_index = build_vector_index()
    app.state.embedder = build_embedder()
    app.state.solver_pool = SolverPool(
        pool_size=settings.z3_pool_size,
        timeout_ms=settings.z3_timeout_ms,
        memory_limit_mb=settings.z3_memory_limit_mb,
    )
    app.state.fetcher = PoliteFetcher()
    app.state.statute_repository = build_statute_repository()
    await app.state.statute_repository.create_schema()

    rehydrated_count = await hydrate_indexes(
        app.state.statute_repository, app.state.graph_service, app.state.vector_index, app.state.embedder
    )
    if rehydrated_count:
        logger.info("rehydrated_indexes_from_statute_repository", count=rehydrated_count)

    try:
        yield
    finally:
        await app.state.fetcher.aclose()
        await app.state.statute_repository.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Legal Engine Platform API", version="1.1.0", lifespan=lifespan)
    add_middleware(app)

    # /auth/token itself must stay unprotected (that's the only way to get a
    # token in the first place); every other router requires it, though
    # require_auth no-ops unless settings.api_auth_enabled is set.
    app.include_router(auth.router, prefix="/auth", tags=["auth"])

    protected = [Depends(require_auth)]
    app.include_router(
        verification.router, prefix="/verification", tags=["verification"], dependencies=protected
    )
    app.include_router(
        simulation.router, prefix="/simulation", tags=["simulation"], dependencies=protected
    )
    app.include_router(
        refactoring.router, prefix="/refactoring", tags=["refactoring"], dependencies=protected
    )
    app.include_router(graph.router, prefix="/graph", tags=["graph"], dependencies=protected)
    app.include_router(
        ingestion.router, prefix="/ingestion", tags=["ingestion"], dependencies=protected
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
