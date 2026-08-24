"""Dependency injection for the API layer.

Every route depends on the Protocol interfaces (GraphService, VectorIndex,
Embedder, StatuteRepository) rather than a concrete class, so which backend
main.py's lifespan actually constructs is a settings change
(knowledge_graph/factory.py, persistence/factory.py), not a route change;
and ``require_auth`` below is a real, working (if deliberately simple) JWT
check, off by default via settings.api_auth_enabled.

``get_current_tenant`` and ``require_auth`` both validate the same bearer
token but for different purposes — ``require_auth`` (applied at the router
level, gating every route in a protected router) answers "is this request
allowed at all," while ``get_current_tenant`` (injected only by the
graph.py routes that actually touch tenant-scoped data — verification/
simulation/refactoring have no persisted state to isolate) answers "which
tenant's data does this request see." Keeping them separate, rather than
unifying into one dependency, costs a small duplicated JWT decode per
request in exchange for each one staying simple and single-purpose.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from legal_engine.api.security import InvalidTokenError, get_token_tenant, verify_token
from legal_engine.compliance.consent import DISCLAIMER_VERSION, ConsentLedger
from legal_engine.core.config import settings
from legal_engine.core.wal import WriteAheadLog
from legal_engine.formal_logic.solver_pool import SolverPool
from legal_engine.ingestion.rate_limiter import PoliteFetcher
from legal_engine.knowledge_graph.embeddings import Embedder
from legal_engine.knowledge_graph.graph_service import GraphService
from legal_engine.knowledge_graph.tenant_registry import TenantIndexRegistry
from legal_engine.knowledge_graph.vector_service import VectorIndex
from legal_engine.persistence.repository import StatuteRepository


async def get_current_tenant(request: Request) -> str:
    """Returns settings.default_tenant_id when auth is disabled (the
    default — the whole deployment behaves as one tenant, unchanged from
    pre-multi-tenancy behavior). When enabled, requires a valid bearer
    token carrying a tenant_id claim."""
    if not settings.api_auth_enabled:
        return settings.default_tenant_id

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        return get_token_tenant(auth_header.removeprefix("Bearer "))
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def get_tenant_registry(request: Request) -> TenantIndexRegistry:
    return request.app.state.tenant_registry


def get_graph_service(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    registry: Annotated[TenantIndexRegistry, Depends(get_tenant_registry)],
) -> GraphService:
    return registry.graph_for(tenant_id)


def get_vector_index(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    registry: Annotated[TenantIndexRegistry, Depends(get_tenant_registry)],
) -> VectorIndex:
    return registry.vector_for(tenant_id)


def get_embedder(request: Request) -> Embedder:
    return request.app.state.embedder


def get_solver_pool(request: Request) -> SolverPool:
    return request.app.state.solver_pool


def get_fetcher(request: Request) -> PoliteFetcher:
    return request.app.state.fetcher


def get_statute_repository(request: Request) -> StatuteRepository:
    return request.app.state.statute_repository


def get_wal(request: Request) -> WriteAheadLog:
    return request.app.state.wal


def get_consent_ledger(request: Request) -> ConsentLedger:
    return request.app.state.consent_ledger


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


async def require_consent(request: Request, tenant_id: Annotated[str, Depends(get_current_tenant)]) -> None:
    """No-ops when settings.api_auth_enabled is False, same as
    require_auth/get_current_tenant — consent enforcement only means
    anything once requests are tied to a real, identified tenant. When
    enabled, 403s unless that tenant has an acceptance-of-the-current-
    disclaimer-version entry on record (see compliance/consent.py's
    ConsentLedger, POST /legal/accept)."""
    if not settings.api_auth_enabled:
        return
    ledger: ConsentLedger = request.app.state.consent_ledger
    if not ledger.has_accepted_current_disclaimer(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Tenant has not accepted disclaimer version {DISCLAIMER_VERSION!r}. "
                "See GET /legal/disclaimer and POST /legal/accept."
            ),
        )


GraphServiceDep = Annotated[GraphService, Depends(get_graph_service)]
VectorIndexDep = Annotated[VectorIndex, Depends(get_vector_index)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
SolverPoolDep = Annotated[SolverPool, Depends(get_solver_pool)]
FetcherDep = Annotated[PoliteFetcher, Depends(get_fetcher)]
StatuteRepositoryDep = Annotated[StatuteRepository, Depends(get_statute_repository)]
WalDep = Annotated[WriteAheadLog, Depends(get_wal)]
ConsentLedgerDep = Annotated[ConsentLedger, Depends(get_consent_ledger)]
TenantIdDep = Annotated[str, Depends(get_current_tenant)]
