"""Liability-disclaimer text and per-tenant acceptance.

GET /disclaimer is deliberately unauthenticated — a tenant should be able
to read what they're being asked to agree to before they have a token to
agree with. POST /accept requires a valid bearer token when auth is
enabled (via its own require_auth dependency, not the router's) because
the acceptance record's whole value is that the *subject* comes from a
server-verified token claim, never a client-supplied field — anyone could
put "totally-legit-lawyer" in a JSON body, nobody can forge what a valid
signature says the token's subject is.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from legal_engine.api.dependencies import TenantIdDep, WalDep, require_auth
from legal_engine.compliance.consent import (
    DISCLAIMER_TEXT,
    DISCLAIMER_VERSION,
    has_accepted_current_disclaimer,
    record_acceptance,
)

router = APIRouter()


class DisclaimerResponse(BaseModel):
    version: str
    text: str


class AcceptanceResponse(BaseModel):
    tenant_id: str
    disclaimer_version: str
    already_accepted: bool


@router.get("/disclaimer", response_model=DisclaimerResponse)
async def get_disclaimer() -> DisclaimerResponse:
    return DisclaimerResponse(version=DISCLAIMER_VERSION, text=DISCLAIMER_TEXT)


@router.post("/accept", response_model=AcceptanceResponse)
async def accept_disclaimer(
    tenant_id: TenantIdDep,
    subject: Annotated[str | None, Depends(require_auth)],
    wal: WalDep,
) -> AcceptanceResponse:
    already = has_accepted_current_disclaimer(wal, tenant_id)
    if not already:
        record_acceptance(wal, tenant_id, subject=subject or tenant_id)
    return AcceptanceResponse(
        tenant_id=tenant_id, disclaimer_version=DISCLAIMER_VERSION, already_accepted=already
    )
