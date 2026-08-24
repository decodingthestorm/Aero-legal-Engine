"""Token issuance, plus self-service tenant/user registration.

POST /token predates POST /register: there's still exactly one hardcoded
demo credential (settings.api_client_id/api_client_secret) that always
works unconditionally, so zero-config local dev and every pre-existing
test stay unaffected — but it now also checks the real user registry
(persistence/user_repository.py), so a registered user logs in through
the same endpoint, "client_id" doubling as their email.

POST /register always provisions a *brand-new* tenant alongside its first
user — it is not a "join an existing tenant" flow. Inviting a second user
into a tenant that already has one is a real, separate feature (needs an
actual notion of who's allowed to invite whom) this doesn't build. That
scope cut is why UserRepository has no "list users in a tenant" method:
every tenant has exactly one user, for now.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from legal_engine.api.dependencies import UserRepositoryDep
from legal_engine.api.security import create_token, hash_password, verify_password
from legal_engine.core.config import settings
from legal_engine.core.models import UserAccount

router = APIRouter()


class TokenRequest(BaseModel):
    client_id: str
    client_secret: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def _basic_email_shape(cls, value: str) -> str:
        # Not full RFC 5322 validation (that needs the email-validator
        # package — pydantic's EmailStr requires it as an extra
        # dependency this project doesn't otherwise need) — just enough
        # to reject an obviously-not-an-email string before it becomes a
        # login identifier nobody could ever type back in correctly.
        if "@" not in value or value.startswith("@") or value.endswith("@") or " " in value:
            raise ValueError("must look like an email address")
        return value.lower()


class RegisterResponse(BaseModel):
    tenant_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest, user_repository: UserRepositoryDep) -> RegisterResponse:
    if await user_repository.get_by_email(request.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    tenant_id = f"tenant-{uuid4().hex}"
    user = UserAccount(
        tenant_id=tenant_id, email=request.email, password_hash=hash_password(request.password)
    )
    await user_repository.add(user)

    access_token = create_token(subject=user.email, tenant_id=tenant_id)
    refresh_token = create_token(
        subject=user.email,
        tenant_id=tenant_id,
        token_type="refresh",
        expires_minutes=settings.refresh_token_expires_days * 24 * 60,
    )
    return RegisterResponse(
        tenant_id=tenant_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_minutes=settings.jwt_expires_minutes,
    )


@router.post("/token", response_model=TokenResponse)
async def issue_token(request: TokenRequest, user_repository: UserRepositoryDep) -> TokenResponse:
    if request.client_id == settings.api_client_id and request.client_secret == settings.api_client_secret:
        subject, tenant_id = settings.api_client_id, settings.api_client_tenant_id
    else:
        user = await user_repository.get_by_email(request.client_id)
        if user is None or not verify_password(request.client_secret, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid client credentials")
        subject, tenant_id = user.email, user.tenant_id

    access_token = create_token(subject=subject, tenant_id=tenant_id)
    refresh_token = create_token(
        subject=subject,
        tenant_id=tenant_id,
        token_type="refresh",
        expires_minutes=settings.refresh_token_expires_days * 24 * 60,
    )
    return TokenResponse(
        access_token=access_token, refresh_token=refresh_token, expires_in_minutes=settings.jwt_expires_minutes
    )
