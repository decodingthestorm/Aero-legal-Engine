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
unifying into one dependency, costs a small duplicated call to
``_decode_bearer_token`` per request in exchange for each one staying
simple and single-purpose. ``_decode_bearer_token`` itself is shared
between them (unlike the two functions above it) because the header-
parsing/revocation/token_type checks it does are exactly the same
regardless of which claim the caller ultimately wants — duplicating
*that* would just be duplicating the error-prone part for no benefit.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Request, status

from legal_engine.api.security import InvalidTokenError, decode_token
from legal_engine.compliance.consent import DISCLAIMER_VERSION, ConsentLedger
from legal_engine.compliance.token_ledger import TokenLedger
from legal_engine.core.config import settings
from legal_engine.core.email_sender import EmailSender
from legal_engine.core.models import UserAccount
from legal_engine.core.wal import WriteAheadLog
from legal_engine.formal_logic.solver_pool import SolverPool
from legal_engine.ingestion.rate_limiter import PoliteFetcher
from legal_engine.knowledge_graph.embeddings import Embedder
from legal_engine.knowledge_graph.graph_service import GraphService
from legal_engine.knowledge_graph.tenant_registry import TenantIndexRegistry
from legal_engine.knowledge_graph.vector_service import VectorIndex
from legal_engine.persistence.repository import StatuteRepository
from legal_engine.persistence.user_repository import UserRepository


def _decode_bearer_token(request: Request) -> dict[str, Any]:
    """Shared by get_current_tenant/require_auth below. Rejects (401): a
    missing/malformed header, a token that fails decode_token's own
    signature/expiry checks, a non-access token presented here (refresh/
    invite/password_reset/etc tokens are only ever redeemed at their own
    single-purpose endpoint — never valid as a regular bearer token), a
    token whose jti is on record as revoked, or a token whose family_id
    is on record as revoked (compliance/token_ledger.py's TokenLedger —
    the latter is what actually kills a still-unexpired access token
    whose sibling refresh token was reused by an attacker, not just the
    reused refresh token itself)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        payload = decode_token(auth_header.removeprefix("Bearer "))
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if payload.get("token_type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh tokens cannot be used as a bearer token — see POST /auth/refresh",
        )

    token_ledger: TokenLedger = request.app.state.token_ledger
    if token_ledger.is_revoked(payload.get("jti", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    if token_ledger.is_family_revoked(payload.get("family_id", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token's session has been revoked (refresh token reuse was detected)",
        )

    return payload


async def get_current_tenant(request: Request) -> str:
    """Returns settings.default_tenant_id when auth is disabled (the
    default — the whole deployment behaves as one tenant, unchanged from
    pre-multi-tenancy behavior). When enabled, requires a valid bearer
    token carrying a tenant_id claim."""
    if not settings.api_auth_enabled:
        return settings.default_tenant_id

    payload = _decode_bearer_token(request)
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is missing a tenant_id claim"
        )
    return str(tenant_id)


def get_tenant_registry(request: Request) -> TenantIndexRegistry:
    return cast(TenantIndexRegistry, request.app.state.tenant_registry)


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
    return cast(Embedder, request.app.state.embedder)


def get_solver_pool(request: Request) -> SolverPool:
    return cast(SolverPool, request.app.state.solver_pool)


def get_fetcher(request: Request) -> PoliteFetcher:
    return cast(PoliteFetcher, request.app.state.fetcher)


def get_statute_repository(request: Request) -> StatuteRepository:
    return cast(StatuteRepository, request.app.state.statute_repository)


def get_user_repository(request: Request) -> UserRepository:
    return cast(UserRepository, request.app.state.user_repository)


def get_wal(request: Request) -> WriteAheadLog:
    return cast(WriteAheadLog, request.app.state.wal)


def get_consent_ledger(request: Request) -> ConsentLedger:
    return cast(ConsentLedger, request.app.state.consent_ledger)


def get_token_ledger(request: Request) -> TokenLedger:
    return cast(TokenLedger, request.app.state.token_ledger)


def get_email_sender(request: Request) -> EmailSender:
    return cast(EmailSender, request.app.state.email_sender)


async def require_auth(request: Request) -> str | None:
    """No-ops (returns None) when settings.api_auth_enabled is False — the
    default, and what every other test in this suite runs against. When
    enabled, requires a valid, non-revoked, non-refresh ``Authorization:
    Bearer <token>`` header (issued by POST /auth/token or
    /auth/register) and returns the token's subject."""
    if not settings.api_auth_enabled:
        return None

    payload = _decode_bearer_token(request)
    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is missing a subject")
    return str(subject)


async def require_verified_email(
    request: Request, subject: Annotated[str | None, Depends(require_auth)]
) -> None:
    """403s unless the caller's account has a verified email address.

    Three no-op conditions, in order. Auth disabled: there's no identified
    caller to check, same as require_auth/require_consent.
    settings.require_email_verification off (the default): enabling this
    retroactively locks out every account registered before it, so it has
    to be opted into. And the demo credential
    (settings.api_client_id) has no UserAccount at all — it predates
    registration and is checked directly by POST /auth/token — so
    requiring a verification flag it can never have would break the
    zero-config path for no security gain.

    Deliberately *not* applied to the /auth router. Someone who can't get
    past this check still needs POST /auth/verify-email to fix it, and
    gating password reset behind email verification would strand anyone
    who lost access before verifying.
    """
    if not settings.api_auth_enabled or not settings.require_email_verification:
        return
    if subject is None or subject == settings.api_client_id:
        return

    user_repository: UserRepository = request.app.state.user_repository
    user = await user_repository.get_by_email(subject)
    if user is None or not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This account's email address is not verified. "
                "See POST /auth/verify-email."
            ),
        )


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


async def require_owner(subject: str | None, user_repository: UserRepository) -> UserAccount:
    """Shared owner-only gate — originally lived in routes/auth.py (POST
    /invite, then the member-management routes), moved here once
    routes/legal.py's POST /revoke needed the exact same check: "is this
    caller their tenant's owner." No meaningful "who's calling" identity
    exists when settings.api_auth_enabled is off, so any route using this
    simply isn't usable in that mode."""
    if subject is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    caller = await user_repository.get_by_email(subject)
    if caller is None or caller.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a tenant's owner can do this")
    return caller


GraphServiceDep = Annotated[GraphService, Depends(get_graph_service)]
VectorIndexDep = Annotated[VectorIndex, Depends(get_vector_index)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
SolverPoolDep = Annotated[SolverPool, Depends(get_solver_pool)]
FetcherDep = Annotated[PoliteFetcher, Depends(get_fetcher)]
StatuteRepositoryDep = Annotated[StatuteRepository, Depends(get_statute_repository)]
UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]
WalDep = Annotated[WriteAheadLog, Depends(get_wal)]
ConsentLedgerDep = Annotated[ConsentLedger, Depends(get_consent_ledger)]
TokenLedgerDep = Annotated[TokenLedger, Depends(get_token_ledger)]
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
TenantIdDep = Annotated[str, Depends(get_current_tenant)]
