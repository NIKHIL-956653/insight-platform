"""JWT access tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from insight.auth.tokens import (
    ACCESS_TOKEN_TYPE,
    TokenError,
    create_access_token,
    decode_access_token,
)
from insight.config import Settings
from tests.conftest import make_settings

USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def raw_claims(token: str, settings: Settings) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )


class TestMinting:
    def test_round_trip(self, settings: Settings) -> None:
        claims = decode_access_token(create_access_token(USER_ID, settings), settings)
        assert claims.sub == USER_ID
        assert claims.typ == ACCESS_TOKEN_TYPE

    def test_each_token_has_a_unique_jti(self, settings: Settings) -> None:
        """INS-7 needs this to detect refresh-token reuse."""
        a = decode_access_token(create_access_token(USER_ID, settings), settings)
        b = decode_access_token(create_access_token(USER_ID, settings), settings)
        assert a.jti != b.jti

    def test_expiry_honours_the_configured_ttl(self) -> None:
        s = make_settings(access_token_ttl_seconds=900)
        now = datetime.now(UTC)
        claims = decode_access_token(create_access_token(USER_ID, s, now=now), s)
        assert (claims.exp - claims.iat) == timedelta(seconds=900)

    def test_no_workspace_is_baked_into_the_token(self, settings: Settings) -> None:
        """Workspace comes per request, so switching needs no new token and
        a revoked membership takes effect immediately."""
        claims = raw_claims(create_access_token(USER_ID, settings), settings)
        assert "workspace_id" not in claims
        assert "workspace" not in claims

    def test_token_carries_no_personal_data(self, settings: Settings) -> None:
        """A JWT is signed, not encrypted - anyone holding it can read it."""
        claims = raw_claims(create_access_token(USER_ID, settings), settings)
        assert set(claims) == {"sub", "jti", "typ", "iat", "exp"}


class TestRejection:
    def test_expired_token_is_rejected(self, settings: Settings) -> None:
        past = datetime.now(UTC) - timedelta(days=1)
        token = create_access_token(USER_ID, settings, now=past)
        with pytest.raises(TokenError, match="expired"):
            decode_access_token(token, settings)

    def test_token_signed_with_another_secret_is_rejected(self, settings: Settings) -> None:
        other = make_settings(jwt_secret="9c2e" * 16)
        token = create_access_token(USER_ID, other)
        with pytest.raises(TokenError, match="invalid"):
            decode_access_token(token, settings)

    def test_tampered_payload_is_rejected(self, settings: Settings) -> None:
        header, _, signature = create_access_token(USER_ID, settings).split(".")
        forged = jwt.utils.base64url_encode(b'{"sub":"attacker"}').decode()
        with pytest.raises(TokenError):
            decode_access_token(f"{header}.{forged}.{signature}", settings)

    def test_a_refresh_token_is_not_accepted_as_an_access_token(self, settings: Settings) -> None:
        """Token confusion: without the typ check, INS-7's long-lived
        refresh token would be usable anywhere an access token is."""
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": str(USER_ID),
                "jti": str(uuid.uuid4()),
                "typ": "refresh",
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(days=14)).timestamp()),
            },
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError, match="not an access token"):
            decode_access_token(token, settings)

    @pytest.mark.parametrize("missing", ["sub", "jti", "typ", "exp", "iat"])
    def test_every_required_claim_is_required(self, settings: Settings, missing: str) -> None:
        now = datetime.now(UTC)
        payload = {
            "sub": str(USER_ID),
            "jti": str(uuid.uuid4()),
            "typ": ACCESS_TOKEN_TYPE,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        }
        del payload[missing]
        token = jwt.encode(
            payload,
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError):
            decode_access_token(token, settings)

    def test_malformed_subject_is_rejected(self, settings: Settings) -> None:
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": "not-a-uuid",
                "jti": str(uuid.uuid4()),
                "typ": ACCESS_TOKEN_TYPE,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=5)).timestamp()),
            },
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError, match="malformed"):
            decode_access_token(token, settings)

    @pytest.mark.parametrize("rubbish", ["", "not.a.token", "a.b", "....", "Bearer x"])
    def test_rubbish_is_rejected(self, settings: Settings, rubbish: str) -> None:
        with pytest.raises(TokenError):
            decode_access_token(rubbish, settings)
