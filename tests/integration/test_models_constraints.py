"""The database actually enforcing what the models declare.

A CHECK constraint that SQLAlchemy renders is not proof that Postgres
enforces it, and these invariants are the ones that keep two accounts from
existing for the same person.

Requires `alembic upgrade head`. Every test rolls back, so nothing persists.

    pytest -m integration
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from insight.config import Settings, get_settings
from insight.db.session import create_engine, create_session_factory
from insight.models import Membership, User, Workspace, WorkspaceRole

pytestmark = pytest.mark.integration


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    get_settings.cache_clear()
    settings: Settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


def _slug() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


def _email() -> str:
    return f"t-{uuid.uuid4().hex[:12]}@example.com"


class TestHappyPath:
    async def test_workspace_user_and_membership_round_trip(self, session: AsyncSession) -> None:
        ws = Workspace(name="Acme Board", slug=_slug())
        user = User(email=_email(), display_name="Test User")
        session.add_all([ws, user])
        await session.flush()

        session.add(Membership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.ADMIN))
        await session.flush()

        assert isinstance(ws.id, uuid.UUID)
        assert ws.created_at is not None
        assert ws.created_at.tzinfo is not None

    async def test_role_defaults_to_member(self, session: AsyncSession) -> None:
        ws = Workspace(name="Defaults", slug=_slug())
        user = User(email=_email(), display_name="Test User")
        session.add_all([ws, user])
        await session.flush()

        m = Membership(workspace_id=ws.id, user_id=user.id)
        session.add(m)
        await session.flush()
        await session.refresh(m)
        assert m.role is WorkspaceRole.MEMBER


class TestEmailIdentity:
    async def test_same_email_twice_is_rejected(self, session: AsyncSession) -> None:
        email = _email()
        session.add(User(email=email, display_name="First"))
        await session.flush()
        session.add(User(email=email, display_name="Second"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_uppercase_email_is_rejected(self, session: AsyncSession) -> None:
        """Normalisation is enforced by the database, not trusted from code."""
        session.add(User(email="Alice@Example.com", display_name="Alice"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_email_without_a_local_part_is_rejected(self, session: AsyncSession) -> None:
        session.add(User(email="@example.com", display_name="Nobody"))
        with pytest.raises(IntegrityError):
            await session.flush()


class TestWorkspaceConstraints:
    async def test_duplicate_slug_is_rejected(self, session: AsyncSession) -> None:
        slug = _slug()
        session.add(Workspace(name="One", slug=slug))
        await session.flush()
        session.add(Workspace(name="Two", slug=slug))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_uppercase_slug_is_rejected(self, session: AsyncSession) -> None:
        session.add(Workspace(name="Shouty", slug="ACME"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_blank_name_is_rejected(self, session: AsyncSession) -> None:
        session.add(Workspace(name="   ", slug=_slug()))
        with pytest.raises(IntegrityError):
            await session.flush()


class TestMembershipConstraints:
    async def test_a_user_joins_a_workspace_once(self, session: AsyncSession) -> None:
        ws = Workspace(name="Once", slug=_slug())
        user = User(email=_email(), display_name="Test User")
        session.add_all([ws, user])
        await session.flush()

        session.add(Membership(workspace_id=ws.id, user_id=user.id))
        await session.flush()
        session.add(Membership(workspace_id=ws.id, user_id=user.id))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_membership_needs_a_real_workspace(self, session: AsyncSession) -> None:
        user = User(email=_email(), display_name="Test User")
        session.add(user)
        await session.flush()

        session.add(Membership(workspace_id=uuid.uuid4(), user_id=user.id))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_one_user_can_join_several_workspaces(self, session: AsyncSession) -> None:
        """The portal's workspace switcher depends on this."""
        user = User(email=_email(), display_name="Multi")
        a = Workspace(name="A", slug=_slug())
        b = Workspace(name="B", slug=_slug())
        session.add_all([user, a, b])
        await session.flush()

        session.add_all(
            [
                Membership(workspace_id=a.id, user_id=user.id),
                Membership(workspace_id=b.id, user_id=user.id),
            ]
        )
        await session.flush()
