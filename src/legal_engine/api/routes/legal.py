"""Liability-disclaimer text and per-tenant acceptance.

GET /disclaimer is deliberately unauthenticated — a tenant should be able
to read what they're being asked to agree to before they have a token to
agree with. POST /accept requires a valid bearer token when auth is
enabled (via its own require_auth dependency, not the router's) because
the acceptance record's whole value is that the *subject* comes from a
server-verified token claim, never a client-supplied field — anyone could
put "totally-legit-lawyer" in a JSON body, nobody can forge what a valid
signature says the token's subject is.

POST /revoke (owner-only, via the same require_owner dependency
api/routes/auth.py's member-management routes use — this literally *is*
"who's an authorized signer for this tenant") lets a tenant withdraw its
acceptance, e.g. because the person who accepted is no longer with the
organization. No token-level cascade is needed the way member removal
needed one: require_consent (api/dependencies.py) re-checks
has_accepted_current_disclaimer fresh on every /verification and
/simulation call, so a revocation blocks further gated requests for that
tenant immediately, with no other wiring.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from legal_engine.api.dependencies import (
    ConsentLedgerDep,
    TenantIdDep,
    UserRepositoryDep,
    require_auth,
    require_owner,
)
from legal_engine.compliance.consent import DISCLAIMER_TEXT, DISCLAIMER_VERSION

router = APIRouter()


class DisclaimerResponse(BaseModel):
    version: str
    text: str


class AcceptanceResponse(BaseModel):
    tenant_id: str
    disclaimer_version: str
    already_accepted: bool


class RevokeAcceptanceRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class RevokeAcceptanceResponse(BaseModel):
    tenant_id: str
    revoked: bool


@router.get("/disclaimer", response_model=DisclaimerResponse)
async def get_disclaimer() -> DisclaimerResponse:
    return DisclaimerResponse(version=DISCLAIMER_VERSION, text=DISCLAIMER_TEXT)


@router.post("/accept", response_model=AcceptanceResponse)
async def accept_disclaimer(
    tenant_id: TenantIdDep,
    subject: Annotated[str | None, Depends(require_auth)],
    ledger: ConsentLedgerDep,
) -> AcceptanceResponse:
    already = ledger.has_accepted_current_disclaimer(tenant_id)
    if not already:
        ledger.record_acceptance(tenant_id, subject=subject or tenant_id)
    return AcceptanceResponse(
        tenant_id=tenant_id, disclaimer_version=DISCLAIMER_VERSION, already_accepted=already
    )


@router.post("/revoke", response_model=RevokeAcceptanceResponse)
async def revoke_disclaimer_acceptance(
    request: RevokeAcceptanceRequest,
    tenant_id: TenantIdDep,
    subject: Annotated[str | None, Depends(require_auth)],
    user_repository: UserRepositoryDep,
    ledger: ConsentLedgerDep,
) -> RevokeAcceptanceResponse:
    await require_owner(subject, user_repository)
    ledger.revoke_acceptance(tenant_id, reason=request.reason)
    return RevokeAcceptanceResponse(tenant_id=tenant_id, revoked=True)
