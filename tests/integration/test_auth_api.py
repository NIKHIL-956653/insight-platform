"""POST /v1/auth/login and GET /v1/auth/me against a real database.

The app's get_session dependency is overridden with the test session, so
everything a test writes shares one transaction that is rolled back at the
end. Nothing persists.

    pytest -m integration
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from insight.auth.password import hash_password
from insight.config import Settings, get_settings
from insight.db.session import create_engine, create_session_factory, get_session
from insight.main import create_app
from insight.models import Membership, User, Workspace, WorkspaceRole

pytestmark = pytest.mark.integration

PASSWORD = "a-real-password-for-testing"


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    get_settings.cache_clear()
    engine = create_engine(get_settings())
    async with create_session_factory(engine)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    settings: Settings = get_settings()
    app = create_app(settings)

    async def _session() -> AsyncIterator[AsyncSession]:
        # Deliberately no commit: the fixture's rollback is what cleans up.
        yield db

    app.dependency_overrides[get_session] = _session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def make_user(
    db: AsyncSession,
    *,
    password: str | None = PASSWORD,
    is_active: bool = True,
) -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:12]}@example.com",
        display_name="Test User",
        password_hash=hash_password(password) if password else None,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user


class TestLoginSucceeds:
    async def test_valid_credentials_return_a_bearer_token(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        user = await make_user(db)
        r = await client.post("/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        assert body["access_token"].count(".") == 2

    async def test_email_is_matched_case_insensitively(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        user = await make_user(db)
        r = await client.post(
            "/v1/auth/login",
            json={"email": user.email.upper(), "password": PASSWORD},
        )
        assert r.status_code == 200

    async def test_last_login_is_recorded(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        user = await make_user(db)
        assert user.last_login_at is None
        await client.post("/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        await db.refresh(user)
        assert user.last_login_at is not None


class TestLoginFails:
    """Every rejection returns the same 401 with the same body - anything
    else is an account-enumeration oracle."""

    async def test_wrong_password(self, client: httpx.AsyncClient, db: AsyncSession) -> None:
        user = await make_user(db)
        r = await client.post("/v1/auth/login", json={"email": user.email, "password": "wrong"})
        assert r.status_code == 401

    async def test_unknown_email(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/v1/auth/login",
            json={"email": "nobody@example.com", "password": PASSWORD},
        )
        assert r.status_code == 401

    async def test_deactivated_user(self, client: httpx.AsyncClient, db: AsyncSession) -> None:
        user = await make_user(db, is_active=False)
        r = await client.post("/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert r.status_code == 401

    async def test_sso_only_user_cannot_use_the_password_path(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        user = await make_user(db, password=None)
        r = await client.post("/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert r.status_code == 401

    async def test_all_rejections_are_byte_identical(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        user = await make_user(db)
        wrong_password = await client.post(
            "/v1/auth/login", json={"email": user.email, "password": "wrong"}
        )
        unknown_email = await client.post(
            "/v1/auth/login",
            json={"email": "nobody@example.com", "password": PASSWORD},
        )
        assert wrong_password.json() == unknown_email.json()

    async def test_malformed_email_is_a_validation_error(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/v1/auth/login", json={"email": "not-an-email", "password": PASSWORD}
        )
        assert r.status_code == 422

    async def test_oversized_password_is_rejected_before_hashing(
        self, client: httpx.AsyncClient
    ) -> None:
        """Argon2 is memory-hard; unbounded input is a cheap DoS."""
        r = await client.post(
            "/v1/auth/login",
            json={"email": "a@example.com", "password": "x" * 2000},
        )
        assert r.status_code == 422


class TestMe:
    async def test_requires_a_token(self, client: httpx.AsyncClient) -> None:
        r = await client.get("/v1/auth/me")
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"

    async def test_rejects_a_rubbish_token(self, client: httpx.AsyncClient) -> None:
        r = await client.get("/v1/auth/me", headers={"Authorization": "Bearer not-a-token"})
        assert r.status_code == 401

    async def test_returns_identity_and_no_workspaces_when_unassigned(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        user = await make_user(db)
        login = await client.post(
            "/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )
        token = login.json()["access_token"]

        r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == user.email
        assert body["workspaces"] == []

    async def test_lists_every_workspace_the_user_belongs_to(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        """This is what drives the portal's workspace switcher."""
        user = await make_user(db)
        alpha = Workspace(name="Alpha", slug=f"a-{uuid.uuid4().hex[:10]}")
        beta = Workspace(name="Beta", slug=f"b-{uuid.uuid4().hex[:10]}")
        db.add_all([alpha, beta])
        await db.flush()
        db.add_all(
            [
                Membership(workspace_id=alpha.id, user_id=user.id, role=WorkspaceRole.OWNER),
                Membership(workspace_id=beta.id, user_id=user.id, role=WorkspaceRole.VIEWER),
            ]
        )
        await db.flush()

        login = await client.post(
            "/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )
        r = await client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        workspaces = r.json()["workspaces"]
        assert [w["name"] for w in workspaces] == ["Alpha", "Beta"]
        assert [w["role"] for w in workspaces] == ["owner", "viewer"]

    async def test_inactive_workspaces_are_hidden(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        user = await make_user(db)
        ws = Workspace(name="Closed", slug=f"c-{uuid.uuid4().hex[:10]}", is_active=False)
        db.add(ws)
        await db.flush()
        db.add(Membership(workspace_id=ws.id, user_id=user.id))
        await db.flush()

        login = await client.post(
            "/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )
        r = await client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert r.json()["workspaces"] == []

    async def test_a_token_stops_working_once_the_user_is_deactivated(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        """Access tokens are stateless, so deactivation has to be enforced
        on every request rather than at issue time."""
        user = await make_user(db)
        login = await client.post(
            "/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert (await client.get("/v1/auth/me", headers=headers)).status_code == 200

        user.is_active = False
        await db.flush()
        assert (await client.get("/v1/auth/me", headers=headers)).status_code == 401
