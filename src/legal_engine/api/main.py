"""FastAPI application entry point.

Constructs the shared in-process state (graph, vector index, embedder,
solver pool, HTTP fetcher) once at startup via ``lifespan`` and tears down
the fetcher's connection pool on shutdown. See api/dependencies.py for why
these are the Protocol-typed in-memory defaults rather than
Neo4j/Qdrant/live-network-backed instances.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from legal_engine.api.middleware import add_middleware
from legal_engine.api.routes import graph, ingestion, refactoring, simulation, verification
from legal_engine.core.config import settings
from legal_engine.core.logging import configure_logging
from legal_engine.formal_logic.solver_pool import SolverPool
from legal_engine.ingestion.rate_limiter import PoliteFetcher
from legal_engine.knowledge_graph.embeddings import HashingEmbedder
from legal_engine.knowledge_graph.graph_service import NetworkXGraphService
from legal_engine.knowledge_graph.vector_service import InMemoryVectorIndex


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    app.state.graph_service = NetworkXGraphService()
    app.state.vector_index = InMemoryVectorIndex()
    app.state.embedder = HashingEmbedder()
    app.state.solver_pool = SolverPool(
        pool_size=settings.z3_pool_size,
        timeout_ms=settings.z3_timeout_ms,
        memory_limit_mb=settings.z3_memory_limit_mb,
    )
    app.state.fetcher = PoliteFetcher()
    try:
        yield
    finally:
        await app.state.fetcher.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Legal Engine Platform API", version="0.1.0", lifespan=lifespan)
    add_middleware(app)

    app.include_router(verification.router, prefix="/verification", tags=["verification"])
    app.include_router(simulation.router, prefix="/simulation", tags=["simulation"])
    app.include_router(refactoring.router, prefix="/refactoring", tags=["refactoring"])
    app.include_router(graph.router, prefix="/graph", tags=["graph"])
    app.include_router(ingestion.router, prefix="/ingestion", tags=["ingestion"])

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
