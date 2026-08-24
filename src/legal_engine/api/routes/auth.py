"""Token issuance, self-service tenant/user registration, tenant invites,
and token lifecycle (refresh rotation, revocation).

POST /token predates POST /register: there's still exactly one hardcoded
demo credential (settings.api_client_id/api_client_secret) that always
works unconditionally, so zero-config local dev and every pre-existing
test stay unaffected — but it now also checks the real user registry
(persistence/user_repository.py), so a registered user logs in through
the same endpoint, "client_id" doubling as their email.

POST /register always provisions a *brand-new* tenant alongside its first
user, who becomes that tenant's "owner" (UserAccount.role — see
core/models.py). It is not a "join an existing tenant" flow — that's what
POST /invite (owner-only) + POST /accept-invite (public, gated by
possessing a valid invite token) are for: an owner invites an email,
gets back an invite_token (would be emailed in a real deployment — see
compliance/email_sender.py once that lands; for now it's returned
directly), and whoever holds that token can accept it to become a
"member" of the *same* tenant. Single-use: accepting revokes the invite
token's jti via the same TokenLedger POST /revoke already uses, so a
second acceptance attempt with the same token is rejected.

POST /refresh redeems a still-valid, not-yet-used refresh token for a new
access+refresh pair — single-use rotation (compliance/token_ledger.py):
the old refresh token is spent the instant it's used, so a second attempt
to reuse it (theft signal) revokes the whole session (see
compliance/token_ledger.py's family_id) rather than silently succeeding.

POST /revoke: possession of a token (access or refresh) is the
authorization to revoke it — matches ordinary "logout" semantics, no
separate auth check needed beyond having the token itself.
"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from legal_engine.api.dependencies import (
    TenantIdDep,
    TokenLedgerDep,
    UserRepositoryDep,
    require_auth,
)
from legal_engine.api.security import (
    InvalidTokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from legal_engine.core.config import settings
from legal_engine.core.models import UserAccount

router = APIRouter()


def _validate_email_shape(value: str) -> str:
    # Not full RFC 5322 validation (that needs the email-validator
    # package — pydantic's EmailStr requires it as an extra dependency
    # this project doesn't otherwise need) — just enough to reject an
    # obviously-not-an-email string before it becomes a login identifier
    # (or invite target) nobody could ever type back in correctly.
    if "@" not in value or value.startswith("@") or value.endswith("@") or " " in value:
        raise ValueError("must look like an email address")
    return value.lower()


def _issue_token_pair(subject: str, tenant_id: str, family_id: str | None = None) -> tuple[str, str]:
    """A fresh login (POST /auth/register, /auth/token) calls this with no
    family_id — a new session, new family. POST /auth/refresh calls it
    with the *old* refresh token's family_id, so the rotated pair stays
    in the same family (see compliance/token_ledger.py for why that's
    what lets a reuse-detected rotation cascade-revoke the sibling access
    token too, not just the reused refresh token)."""
    if family_id is None:
        family_id = str(uuid4())
    access_token = create_token(subject=subject, tenant_id=tenant_id, family_id=family_id)
    refresh_token = create_token(
        subject=subject,
        tenant_id=tenant_id,
        token_type="refresh",
        family_id=family_id,
        expires_minutes=settings.refresh_token_expires_days * 24 * 60,
    )
    return access_token, refresh_token


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

    _check_email = field_validator("email")(_validate_email_shape)


class RegisterResponse(BaseModel):
    tenant_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class InviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    _check_email = field_validator("email")(_validate_email_shape)


class InviteResponse(BaseModel):
    invite_token: str
    expires_in_minutes: int


class AcceptInviteRequest(BaseModel):
    invite_token: str
    password: str = Field(min_length=8, max_length=256)


class AcceptInviteResponse(BaseModel):
    tenant_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class RefreshRequest(BaseModel):
    refresh_token: str


class RevokeRequest(BaseModel):
    token: str


class RevokeResponse(BaseModel):
    revoked: bool


@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest, user_repository: UserRepositoryDep) -> RegisterResponse:
    if await user_repository.get_by_email(request.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    tenant_id = f"tenant-{uuid4().hex}"
    user = UserAccount(
        tenant_id=tenant_id, email=request.email, password_hash=hash_password(request.password)
    )
    await user_repository.add(user)

    access_token, refresh_token = _issue_token_pair(user.email, tenant_id)
    return RegisterResponse(
        tenant_id=tenant_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_minutes=settings.jwt_expires_minutes,
    )


@router.post("/invite", response_model=InviteResponse)
async def invite(
    request: InviteRequest,
    subject: Annotated[str | None, Depends(require_auth)],
    tenant_id: TenantIdDep,
    user_repository: UserRepositoryDep,
) -> InviteResponse:
    if subject is None:
        # require_auth returns None only when settings.api_auth_enabled is
        # off — invites are inherently a real-multi-tenant feature, so
        # there's no meaningful "who's inviting" identity to check in
        # that mode.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    inviter = await user_repository.get_by_email(subject)
    if inviter is None or inviter.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only a tenant's owner can send invites"
        )
    if await user_repository.get_by_email(request.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    expires_minutes = settings.invite_token_expires_days * 24 * 60
    invite_token = create_token(
        subject=request.email, tenant_id=tenant_id, token_type="invite", expires_minutes=expires_minutes
    )
    # Would be emailed to request.email in a real deployment
    # (compliance/email_sender.py) — returned directly here too so the
    # flow is usable and testable without a real inbox.
    return InviteResponse(invite_token=invite_token, expires_in_minutes=expires_minutes)


@router.post("/accept-invite", response_model=AcceptInviteResponse)
async def accept_invite(
    request: AcceptInviteRequest, user_repository: UserRepositoryDep, token_ledger: TokenLedgerDep
) -> AcceptInviteResponse:
    try:
        payload = decode_token(request.invite_token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if payload.get("token_type") != "invite":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not an invite token")

    email = payload.get("sub", "")
    tenant_id = payload.get("tenant_id", "")
    jti = payload.get("jti", "")

    if token_ledger.is_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invite has already been used or revoked"
        )
    if await user_repository.get_by_email(email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = UserAccount(
        tenant_id=tenant_id, email=email, password_hash=hash_password(request.password), role="member"
    )
    await user_repository.add(user)
    # Single-use: reuses the same revocation mechanism POST /revoke uses,
    # rather than a second bookkeeping structure — an "already used"
    # invite token is functionally identical to a revoked one.
    token_ledger.revoke(jti, tenant_id, reason="invite accepted")

    access_token, refresh_token = _issue_token_pair(user.email, tenant_id)
    return AcceptInviteResponse(
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

    access_token, refresh_token = _issue_token_pair(subject, tenant_id)
    return TokenResponse(
        access_token=access_token, refresh_token=refresh_token, expires_in_minutes=settings.jwt_expires_minutes
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest, token_ledger: TokenLedgerDep) -> TokenResponse:
    try:
        payload = decode_token(request.refresh_token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if payload.get("token_type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")

    subject = payload.get("sub", "")
    tenant_id = payload.get("tenant_id", "")
    jti = payload.get("jti", "")
    family_id = payload.get("family_id", "")
    if not token_ledger.redeem_refresh_token(jti, tenant_id, family_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has already been used or revoked",
        )

    access_token, new_refresh_token = _issue_token_pair(subject, tenant_id, family_id=family_id)
    return TokenResponse(
        access_token=access_token, refresh_token=new_refresh_token, expires_in_minutes=settings.jwt_expires_minutes
    )


@router.post("/revoke", response_model=RevokeResponse)
async def revoke(request: RevokeRequest, token_ledger: TokenLedgerDep) -> RevokeResponse:
    try:
        payload = decode_token(request.token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    token_ledger.revoke(
        payload.get("jti", ""), payload.get("tenant_id", ""), reason="client-requested revocation"
    )
    return RevokeResponse(revoked=True)
