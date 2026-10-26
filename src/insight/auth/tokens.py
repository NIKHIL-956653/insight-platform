"""JWT access tokens.

Access tokens are short-lived and stateless: nothing is looked up to
validate one, which is what makes them cheap. The cost of that is they
cannot be revoked before they expire - hence the short TTL, and hence
refresh tokens, which are stateful and revocable, in INS-7.

Deliberately *not* in the token: the active workspace. A user belongs to
several, and baking one in would mean a new token to switch, and a revoked
membership staying usable until expiry. The workspace arrives per request
and is checked against memberships (INS-8).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
from pydantic import BaseModel

from insight.config import Settings

ACCESS_TOKEN_TYPE: Final = "access"  # noqa: S105 - a type discriminator, not a secret


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired or not ours."""


class AccessTokenClaims(BaseModel):
    """Validated claims from an access token."""

    sub: uuid.UUID
    jti: uuid.UUID
    typ: str
    iat: datetime
    exp: datetime


def create_access_token(
    user_id: uuid.UUID,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> str:
    """Mint a short-lived access token for a user.

    `now` is injectable so tests can prove expiry without sleeping.
    """
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=settings.access_token_ttl_seconds)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        # A unique id per token. Unused by access tokens today; INS-7 needs
        # it to detect refresh-token reuse, and having it from the start
        # means the audit trail can reference a specific token.
        "jti": str(uuid.uuid4()),
        # Distinguishes access from refresh. Without it, a refresh token
        # would be accepted anywhere an access token is - the classic
        # token-confusion bug.
        "typ": ACCESS_TOKEN_TYPE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    """Verify and decode an access token.

    Raises TokenError for every failure, so a caller cannot mistake a
    rejected token for a valid one.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            # A list, never a bare string, and never from the token itself.
            # Trusting the token's own `alg` header is how "alg: none" and
            # the HS256/RS256 confusion attack work.
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "jti", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token is invalid") from exc

    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        raise TokenError("not an access token")

    try:
        return AccessTokenClaims(
            sub=uuid.UUID(payload["sub"]),
            jti=uuid.UUID(payload["jti"]),
            typ=payload["typ"],
            iat=datetime.fromtimestamp(payload["iat"], tz=UTC),
            exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise TokenError("token claims are malformed") from exc
