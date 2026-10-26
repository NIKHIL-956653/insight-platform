"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from insight.auth.tokens import TokenError, decode_access_token
from insight.config import Settings
from insight.db.session import get_session
from insight.models import User

# auto_error=False so a missing header produces our own 401 with a
# WWW-Authenticate challenge, rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_app_settings(request: Request) -> Settings:
    """Settings as attached to the app, so tests can inject their own."""
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Resolve the bearer token to a live, active user.

    Every failure returns the same 401 with the same body. Distinguishing
    "no such user" from "deactivated" from "bad signature" would tell an
    attacker which tokens are worth attacking.
    """
    if credentials is None:
        raise CREDENTIALS_EXCEPTION

    try:
        claims = decode_access_token(credentials.credentials, settings)
    except TokenError:
        raise CREDENTIALS_EXCEPTION from None

    user = await session.scalar(select(User).where(User.id == claims.sub))

    # The token may outlive the account: it is stateless and valid until it
    # expires, so deactivation has to be enforced here on every request.
    if user is None or not user.is_active:
        raise CREDENTIALS_EXCEPTION

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
