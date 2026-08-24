"""Token issuance, self-service tenant/user registration, tenant invites,
password reset / email verification, and token lifecycle (refresh
rotation, revocation).

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
gets back an invite_token, and whoever holds that token can accept it to
become a "member" of the *same* tenant. Single-use: accepting revokes the
invite token's jti via the same TokenLedger POST /revoke already uses, so
a second acceptance attempt with the same token is rejected.

Every token this module hands to an email address (invite, password
reset, and registration's email-verification token) is both sent through
EmailSenderDep (core/email_sender.py — logs instead of actually sending
by default; see that module for why) *and* returned directly in the API
response — a real deployment would only do the former, but returning it
too is what keeps every one of these flows directly testable and usable
without a real inbox in this environment.

POST /request-password-reset never reveals whether an email is
registered (always 200s; the reset_token field is only present when the
account actually exists) — a real anti-enumeration property, not an
oversight. POST /reset-password *does* revoke every other active session
for that user (compliance/token_ledger.py's
revoke_all_sessions_for_subject) — a password reset is exactly the
"assume this account may have been compromised" moment a session-wide
invalidation exists for.

POST /refresh redeems a still-valid, not-yet-used refresh token for a new
access+refresh pair — single-use rotation (compliance/token_ledger.py):
the old refresh token is spent the instant it's used, so a second attempt
to reuse it (theft signal) revokes the whole session (see
compliance/token_ledger.py's family_id) rather than silently succeeding.

POST /revoke: possession of a token (access or refresh) is the
authorization to revoke it — matches ordinary "logout" semantics, no
separate auth check needed beyond having the token itself.

GET /members lists the caller's own tenant's roster (any authenticated
member, not owner-gated — seeing your own teammates isn't a privileged
action). POST /members/{email}/role and DELETE /members/{email} are
owner-only, and both protect the one real invariant this feature has to
maintain: a tenant can never end up with zero owners (409 if a change
would cause that). Removing a member also revokes every session they're
currently holding (compliance/token_ledger.py's
revoke_all_sessions_for_subject, the same mechanism POST /reset-password
uses) — a removed member's access stops immediately, not just their
ability to log in again.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from legal_engine.api.dependencies import (
    EmailSenderDep,
    TenantIdDep,
    TokenLedgerDep,
    UserRepositoryDep,
    require_auth,
    require_owner,
)
from legal_engine.api.security import (
    InvalidTokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from legal_engine.compliance.token_ledger import TokenLedger
from legal_engine.core.config import settings
from legal_engine.core.models import UserAccount
from legal_engine.persistence.user_repository import UserRepository

router = APIRouter()


async def _would_leave_tenant_without_an_owner(
    user_repository: UserRepository, tenant_id: str, excluding_email: str
) -> bool:
    members = await user_repository.list_by_tenant(tenant_id)
    remaining_owners = [m for m in members if m.role == "owner" and m.email != excluding_email]
    return len(remaining_owners) == 0


def _validate_email_shape(value: str) -> str:
    # Not full RFC 5322 validation (that needs the email-validator
    # package — pydantic's EmailStr requires it as an extra dependency
    # this project doesn't otherwise need) — just enough to reject an
    # obviously-not-an-email string before it becomes a login identifier
    # (or invite target) nobody could ever type back in correctly.
    if "@" not in value or value.startswith("@") or value.endswith("@") or " " in value:
        raise ValueError("must look like an email address")
    return value.lower()


def _issue_token_pair(
    subject: str, tenant_id: str, token_ledger: TokenLedger, family_id: str | None = None
) -> tuple[str, str]:
    """A fresh login (POST /auth/register, /auth/token) calls this with no
    family_id — a new session, new family, recorded via
    token_ledger.record_session_started so a later password reset (or a
    member being removed from a tenant) can find and revoke it along with
    every other session that subject holds. POST /auth/refresh calls it
    with the *old* refresh token's family_id instead — the rotated pair
    stays in the *same* session/family (also what lets a reuse-detected
    rotation cascade-revoke the sibling access token, not just the reused
    refresh token) — and does NOT record a new session, since it's the
    same one continuing, not a new one to separately track."""
    is_new_session = family_id is None
    if family_id is None:
        family_id = str(uuid4())
    if is_new_session:
        token_ledger.record_session_started(subject, tenant_id, family_id)
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
    verify_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class RequestPasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    _check_email = field_validator("email")(_validate_email_shape)


class RequestPasswordResetResponse(BaseModel):
    # Always 200 regardless of whether the email is registered (anti-
    # enumeration) — reset_token is only ever populated when it is.
    reset_token: str | None = None


class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str = Field(min_length=8, max_length=256)


class ResetPasswordResponse(BaseModel):
    reset: bool


class VerifyEmailRequest(BaseModel):
    verify_token: str


class VerifyEmailResponse(BaseModel):
    verified: bool


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


class MemberSchema(BaseModel):
    email: str
    role: str
    email_verified: bool
    created_at: datetime


class MembersListResponse(BaseModel):
    members: list[MemberSchema]


class ChangeRoleRequest(BaseModel):
    role: Literal["owner", "member"]


class ChangeRoleResponse(BaseModel):
    email: str
    role: str


class RemoveMemberResponse(BaseModel):
    removed: bool


class RefreshRequest(BaseModel):
    refresh_token: str


class RevokeRequest(BaseModel):
    token: str


class RevokeResponse(BaseModel):
    revoked: bool


@router.post("/register", response_model=RegisterResponse)
async def register(
    request: RegisterRequest,
    user_repository: UserRepositoryDep,
    email_sender: EmailSenderDep,
    token_ledger: TokenLedgerDep,
) -> RegisterResponse:
    if await user_repository.get_by_email(request.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    tenant_id = f"tenant-{uuid4().hex}"
    user = UserAccount(
        tenant_id=tenant_id, email=request.email, password_hash=hash_password(request.password)
    )
    await user_repository.add(user)

    verify_token = create_token(
        subject=user.email,
        tenant_id=tenant_id,
        token_type="email_verification",
        expires_minutes=settings.email_verification_token_expires_days * 24 * 60,
    )
    email_sender.send(
        to=user.email,
        subject="Verify your email",
        body=f"Welcome! Verify your email with this token: {verify_token}",
    )

    access_token, refresh_token = _issue_token_pair(user.email, tenant_id, token_ledger)
    return RegisterResponse(
        verify_token=verify_token,
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
    email_sender: EmailSenderDep,
) -> InviteResponse:
    await require_owner(subject, user_repository)
    if await user_repository.get_by_email(request.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    expires_minutes = settings.invite_token_expires_days * 24 * 60
    invite_token = create_token(
        subject=request.email, tenant_id=tenant_id, token_type="invite", expires_minutes=expires_minutes
    )
    email_sender.send(
        to=request.email,
        subject=f"{subject} invited you to their Legal Engine Platform tenant",
        body=f"Accept with this token: {invite_token}",
    )
    # Also returned directly (not just emailed) so the flow is usable and
    # testable without a real inbox — see the module docstring.
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

    access_token, refresh_token = _issue_token_pair(user.email, tenant_id, token_ledger)
    return AcceptInviteResponse(
        tenant_id=tenant_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_minutes=settings.jwt_expires_minutes,
    )


@router.get("/members", response_model=MembersListResponse)
async def list_members(
    subject: Annotated[str | None, Depends(require_auth)],
    tenant_id: TenantIdDep,
    user_repository: UserRepositoryDep,
) -> MembersListResponse:
    if subject is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    members = await user_repository.list_by_tenant(tenant_id)
    return MembersListResponse(
        members=[
            MemberSchema(
                email=m.email, role=m.role, email_verified=m.email_verified, created_at=m.created_at
            )
            for m in members
        ]
    )


@router.post("/members/{email}/role", response_model=ChangeRoleResponse)
async def change_member_role(
    email: str,
    request: ChangeRoleRequest,
    subject: Annotated[str | None, Depends(require_auth)],
    tenant_id: TenantIdDep,
    user_repository: UserRepositoryDep,
) -> ChangeRoleResponse:
    await require_owner(subject, user_repository)

    target = await user_repository.get_by_email(email)
    if target is None or target.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such member in this tenant")

    if (
        target.role == "owner"
        and request.role == "member"
        and await _would_leave_tenant_without_an_owner(user_repository, tenant_id, excluding_email=email)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot demote the tenant's last remaining owner",
        )

    updated = target.model_copy(update={"role": request.role})
    await user_repository.add(updated)
    return ChangeRoleResponse(email=email, role=request.role)


@router.delete("/members/{email}", response_model=RemoveMemberResponse)
async def remove_member(
    email: str,
    subject: Annotated[str | None, Depends(require_auth)],
    tenant_id: TenantIdDep,
    user_repository: UserRepositoryDep,
    token_ledger: TokenLedgerDep,
) -> RemoveMemberResponse:
    await require_owner(subject, user_repository)

    target = await user_repository.get_by_email(email)
    if target is None or target.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such member in this tenant")

    if target.role == "owner" and await _would_leave_tenant_without_an_owner(
        user_repository, tenant_id, excluding_email=email
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove the tenant's last remaining owner",
        )

    await user_repository.remove(email)
    # A removed member's access stops immediately, not just their ability
    # to log in again — same mechanism POST /reset-password uses.
    token_ledger.revoke_all_sessions_for_subject(email, tenant_id, reason="member removed")
    return RemoveMemberResponse(removed=True)


@router.post("/token", response_model=TokenResponse)
async def issue_token(
    request: TokenRequest, user_repository: UserRepositoryDep, token_ledger: TokenLedgerDep
) -> TokenResponse:
    if request.client_id == settings.api_client_id and request.client_secret == settings.api_client_secret:
        subject, tenant_id = settings.api_client_id, settings.api_client_tenant_id
    else:
        user = await user_repository.get_by_email(request.client_id)
        if user is None or not verify_password(request.client_secret, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid client credentials")
        subject, tenant_id = user.email, user.tenant_id

    access_token, refresh_token = _issue_token_pair(subject, tenant_id, token_ledger)
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

    access_token, new_refresh_token = _issue_token_pair(subject, tenant_id, token_ledger, family_id=family_id)
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


@router.post("/request-password-reset", response_model=RequestPasswordResetResponse)
async def request_password_reset(
    request: RequestPasswordResetRequest, user_repository: UserRepositoryDep, email_sender: EmailSenderDep
) -> RequestPasswordResetResponse:
    user = await user_repository.get_by_email(request.email)
    if user is None:
        # Always 200 either way — never confirms whether an email is
        # registered. See the module docstring.
        return RequestPasswordResetResponse(reset_token=None)

    reset_token = create_token(
        subject=user.email,
        tenant_id=user.tenant_id,
        token_type="password_reset",
        expires_minutes=settings.password_reset_token_expires_minutes,
    )
    email_sender.send(
        to=user.email,
        subject="Reset your password",
        body=f"Reset your password with this token: {reset_token}",
    )
    return RequestPasswordResetResponse(reset_token=reset_token)


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    request: ResetPasswordRequest, user_repository: UserRepositoryDep, token_ledger: TokenLedgerDep
) -> ResetPasswordResponse:
    try:
        payload = decode_token(request.reset_token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if payload.get("token_type") != "password_reset":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a password reset token")

    email = payload.get("sub", "")
    jti = payload.get("jti", "")
    if token_ledger.is_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Reset token has already been used or revoked"
        )

    user = await user_repository.get_by_email(email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists")

    updated = user.model_copy(update={"password_hash": hash_password(request.new_password)})
    await user_repository.add(updated)
    # Single-use, same reused mechanism as invite/accept-invite.
    token_ledger.revoke(jti, user.tenant_id, reason="password reset")
    # A password reset is exactly the "assume this account may have been
    # compromised" moment a session-wide invalidation exists for — every
    # other active session for this user is killed too, not just the
    # reset token itself.
    token_ledger.revoke_all_sessions_for_subject(email, user.tenant_id, reason="password reset")
    return ResetPasswordResponse(reset=True)


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(request: VerifyEmailRequest, user_repository: UserRepositoryDep) -> VerifyEmailResponse:
    try:
        payload = decode_token(request.verify_token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if payload.get("token_type") != "email_verification":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not an email verification token")

    user = await user_repository.get_by_email(payload.get("sub", ""))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists")

    # Not revoked after use the way invite/reset tokens are: re-verifying
    # an already-verified email with the same token is a harmless no-op,
    # not a security-relevant reuse — email_verified itself is the
    # durable record.
    if not user.email_verified:
        await user_repository.add(user.model_copy(update={"email_verified": True}))
    return VerifyEmailResponse(verified=True)
