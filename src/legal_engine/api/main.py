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
from pathlib import Path

from fastapi import Depends, FastAPI

from legal_engine.api.dependencies import require_auth, require_consent
from legal_engine.api.middleware import add_middleware
from legal_engine.api.routes import (
    auth,
    graph,
    ingestion,
    legal,
    refactoring,
    simulation,
    verification,
)
from legal_engine.compliance.consent import ConsentLedger
from legal_engine.compliance.token_ledger import TokenLedger
from legal_engine.core.config import settings
from legal_engine.core.email_sender_factory import build_email_sender
from legal_engine.core.key_signer_factory import build_key_signer
from legal_engine.core.logging import configure_logging, get_logger
from legal_engine.core.wal import WriteAheadLog
from legal_engine.formal_logic.solver_pool import SolverPool
from legal_engine.ingestion.rate_limiter import PoliteFetcher
from legal_engine.knowledge_graph.factory import build_embedder
from legal_engine.knowledge_graph.tenant_registry import TenantIndexRegistry
from legal_engine.persistence.factory import build_statute_repository, build_user_repository
from legal_engine.persistence.hydration import hydrate_indexes

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    # Per-tenant GraphService/VectorIndex instances — see
    # knowledge_graph/tenant_registry.py — replace the single shared
    # graph_service/vector_index that pre-multi-tenancy code used to build
    # here directly.
    app.state.tenant_registry = TenantIndexRegistry()
    app.state.embedder = build_embedder()
    app.state.solver_pool = SolverPool(
        pool_size=settings.z3_pool_size,
        timeout_ms=settings.z3_timeout_ms,
        memory_limit_mb=settings.z3_memory_limit_mb,
    )
    app.state.fetcher = PoliteFetcher()
    app.state.statute_repository = build_statute_repository()
    await app.state.statute_repository.create_schema()
    app.state.user_repository = build_user_repository()
    await app.state.user_repository.create_schema()
    app.state.email_sender = build_email_sender()

    # The audit/consent log (core/wal.py, compliance/consent.py). Loads the
    # settings.wal_signer_backend-selected KeySigner (core/key_signer.py,
    # core/key_signer_factory.py) and replays the same JSON-Lines file
    # across restarts — see Ed25519FileKeySigner.load_or_create's
    # docstring for why a fresh random key every startup would silently
    # break verify() on everything recorded before that restart.
    wal_dir = Path(settings.wal_path)
    app.state.wal = WriteAheadLog(build_key_signer(), path=wal_dir / "audit.jsonl")
    # Replays app.state.wal's existing legal_disclaimer_accepted entries
    # once here, so every gated request afterward is an O(1) dict lookup
    # instead of a rescan — see compliance/consent.py's ConsentLedger.
    app.state.consent_ledger = ConsentLedger(app.state.wal)
    # Same replay-on-construction pattern for token revocation / refresh-
    # token redemption tracking — see compliance/token_ledger.py.
    app.state.token_ledger = TokenLedger(app.state.wal)

    rehydrated_count = await hydrate_indexes(
        app.state.statute_repository, app.state.tenant_registry, app.state.embedder
    )
    if rehydrated_count:
        logger.info("rehydrated_indexes_from_statute_repository", count=rehydrated_count)

    try:
        yield
    finally:
        await app.state.fetcher.aclose()
        await app.state.statute_repository.close()
        await app.state.user_repository.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Legal Engine Platform API", version="1.8.0", lifespan=lifespan)
    add_middleware(app)

    # /auth (token/register) and /legal/disclaimer must stay unprotected
    # (the former is the only way to get a token in the first place; the
    # latter should be readable by anyone deciding whether to agree to
    # it). Every other router requires auth, though require_auth no-ops
    # unless settings.api_auth_enabled is set.
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(legal.router, prefix="/legal", tags=["legal"])

    protected = [Depends(require_auth)]
    # verification/simulation additionally require an on-record acceptance
    # of the current liability disclaimer (compliance/consent.py) — these
    # are the two subsystems the disclaimer text is actually about ("formal
    # verification" and "game-theoretic modeling"). require_consent, like
    # require_auth, no-ops unless settings.api_auth_enabled is set.
    consent_gated = [*protected, Depends(require_consent)]
    app.include_router(
        verification.router, prefix="/verification", tags=["verification"], dependencies=consent_gated
    )
    app.include_router(
        simulation.router, prefix="/simulation", tags=["simulation"], dependencies=consent_gated
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
