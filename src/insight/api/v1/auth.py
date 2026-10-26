"""Authentication endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status
from sqlalchemy import func, select

from insight.api.deps import CREDENTIALS_EXCEPTION, CurrentUser, SessionDep, SettingsDep
from insight.auth.password import hash_password, needs_rehash, verify_dummy, verify_password
from insight.auth.tokens import create_access_token
from insight.logging import get_logger
from insight.models import Membership, User, Workspace
from insight.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    TokenResponse,
    WorkspaceSummary,
)

log = get_logger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange email and password for an access token",
)
async def login(
    payload: LoginRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    """Authenticate and issue a short-lived access token.

    Every failure path returns the same 401. "No such account", "wrong
    password" and "deactivated" are indistinguishable to the caller, and
    the no-such-account path still burns an Argon2 verification so the
    response time does not leak which emails are registered.
    """
    user = await session.scalar(select(User).where(func.lower(User.email) == payload.email))

    if user is None:
        verify_dummy()
        log.info("login rejected", reason="no_such_user")
        raise CREDENTIALS_EXCEPTION

    if not verify_password(payload.password, user.password_hash):
        log.info("login rejected", reason="bad_password", user_id=str(user.id))
        raise CREDENTIALS_EXCEPTION

    if not user.is_active:
        log.info("login rejected", reason="inactive", user_id=str(user.id))
        raise CREDENTIALS_EXCEPTION

    # Sign-in is the only moment the plaintext exists, so it is the only
    # moment a weaker hash can be upgraded.
    if user.password_hash is not None and needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        log.info("password hash upgraded", user_id=str(user.id))

    user.last_login_at = datetime.now(UTC)

    log.info("login accepted", user_id=str(user.id))
    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        expires_in=settings.access_token_ttl_seconds,
    )


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="The signed-in user and the workspaces they can reach",
)
async def me(user: CurrentUser, session: SessionDep) -> CurrentUserResponse:
    """Identity plus workspace list - what the portal needs to render its
    switcher in one call.

    Queried explicitly rather than through the relationship: every
    relationship is lazy='raise', and a projection avoids loading whole
    Workspace rows to show four fields.
    """
    rows = await session.execute(
        select(Workspace.id, Workspace.name, Workspace.slug, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id, Workspace.is_active.is_(True))
        .order_by(Workspace.name)
    )

    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        workspaces=[WorkspaceSummary(id=r.id, name=r.name, slug=r.slug, role=r.role) for r in rows],
    )
