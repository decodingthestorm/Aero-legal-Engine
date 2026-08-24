"""Token issuance for the (optional, off-by-default) JWT auth layer.

Trades a client_id/client_secret pair for a short-lived bearer token. There
is exactly one configured client (settings.api_client_id/api_client_secret)
— this is a demo credential check, not a user/tenant management system.
The token it issues carries a real tenant_id claim
(settings.api_client_tenant_id), and that claim is what actually enforces
data isolation downstream (see persistence/repository.py,
knowledge_graph/tenant_registry.py) — but there's still only one tenant
anyone can log in as, since there's no tenant/user registration flow to
create a second one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from legal_engine.api.security import create_token
from legal_engine.core.config import settings

router = APIRouter()


class TokenRequest(BaseModel):
    client_id: str
    client_secret: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


@router.post("/token", response_model=TokenResponse)
async def issue_token(request: TokenRequest) -> TokenResponse:
    if request.client_id != settings.api_client_id or request.client_secret != settings.api_client_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid client credentials")
    token = create_token(subject=request.client_id, tenant_id=settings.api_client_tenant_id)
    return TokenResponse(access_token=token, expires_in_minutes=settings.jwt_expires_minutes)
