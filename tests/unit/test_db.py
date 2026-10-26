"""Database layer: naming conventions, mixins, engine and session wiring.

Nothing here touches a live database - see tests/integration for that.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import DateTime, PrimaryKeyConstraint, Uuid
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.pool import QueuePool

from insight.db.base import NAMING_CONVENTION, Base, TimestampMixin, UUIDPrimaryKeyMixin
from insight.db.session import (
    create_audit_engine,
    create_engine,
    create_session_factory,
    get_session,
)
from insight.main import create_app
from tests.conftest import make_settings


class _Thing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "_test_thing"


class TestNamingConvention:
    """Autogenerate compares constraint names; they must be predictable."""

    def test_convention_is_attached_to_metadata(self) -> None:
        assert Base.metadata.naming_convention == NAMING_CONVENTION

    def test_primary_key_name_is_derived(self) -> None:
        pk = cast(PrimaryKeyConstraint, _Thing.__table__.primary_key)
        assert pk.name == "pk__test_thing"

    def test_every_constraint_kind_is_covered(self) -> None:
        assert set(NAMING_CONVENTION) == {"ix", "uq", "ck", "fk", "pk"}


class TestUUIDPrimaryKey:
    def test_column_is_a_uuid_not_an_integer(self) -> None:
        """Serial ids leak row volume across tenants."""
        column = _Thing.__table__.c.id
        assert isinstance(column.type, Uuid)
        assert column.primary_key is True

    def test_python_default_generates_uuid4(self) -> None:
        default = _Thing.__table__.c.id.default
        assert default is not None
        value = default.arg(None) if callable(default.arg) else default.arg
        assert isinstance(value, uuid.UUID)
        assert value.version == 4

    def test_server_default_covers_non_orm_inserts(self) -> None:
        server_default = _Thing.__table__.c.id.server_default
        assert server_default is not None
        assert "gen_random_uuid" in str(server_default.arg)


class TestTimestamps:
    @pytest.mark.parametrize("name", ["created_at", "updated_at"])
    def test_columns_exist_and_are_not_nullable(self, name: str) -> None:
        column = _Thing.__table__.c[name]
        assert column.nullable is False
        assert column.server_default is not None

    @pytest.mark.parametrize("name", ["created_at", "updated_at"])
    def test_timestamps_are_timezone_aware(self, name: str) -> None:
        """Naive timestamps on a seven-year audit trail are a liability."""
        column_type = cast(DateTime, _Thing.__table__.c[name].type)
        assert column_type.timezone is True

    def test_updated_at_refreshes_on_update(self) -> None:
        assert _Thing.__table__.c.updated_at.onupdate is not None
        assert _Thing.__table__.c.created_at.onupdate is None


class TestEngine:
    def test_engine_uses_the_application_role(self) -> None:
        engine = create_engine(make_settings())
        assert isinstance(engine, AsyncEngine)
        assert engine.url.username == "insight"
        assert engine.url.drivername == "postgresql+asyncpg"

    def test_password_is_not_in_the_rendered_url(self) -> None:
        engine = create_engine(make_settings())
        assert "test-pg-password" not in str(engine.url)

    def test_pool_settings_come_from_config(self) -> None:
        engine = create_engine(make_settings(db_pool_size=3, db_max_overflow=1))
        assert cast(QueuePool, engine.pool).size() == 3

    def test_audit_engine_uses_the_insert_only_role(self) -> None:
        engine = create_audit_engine(make_settings())
        assert engine.url.username == "insight_audit"

    def test_audit_engine_has_no_overflow(self) -> None:
        """A runaway audit writer should block, not open unbounded connections."""
        engine = create_audit_engine(make_settings())
        assert cast(QueuePool, engine.pool)._max_overflow == 0


class TestSessionFactory:
    def test_factory_produces_async_sessions(self) -> None:
        factory = create_session_factory(create_engine(make_settings()))
        assert isinstance(factory(), AsyncSession)

    def test_expire_on_commit_is_off(self) -> None:
        """Otherwise reading an attribute after commit triggers a lazy load
        on a closed async session, which raises."""
        factory = create_session_factory(create_engine(make_settings()))
        assert factory.kw["expire_on_commit"] is False


class TestGetSession:
    @staticmethod
    def _request(session: Any) -> Any:
        request = MagicMock()
        request.app.state.session_factory = MagicMock(return_value=session)
        return request

    async def test_commits_when_the_handler_succeeds(self) -> None:
        session = AsyncMock()
        agen = cast(AsyncGenerator[AsyncSession], get_session(self._request(session)))
        assert await agen.__anext__() is session
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()
        session.close.assert_awaited_once()

    async def test_rolls_back_when_the_handler_raises(self) -> None:
        session = AsyncMock()
        agen = cast(AsyncGenerator[AsyncSession], get_session(self._request(session)))
        await agen.__anext__()
        with pytest.raises(RuntimeError):
            await agen.athrow(RuntimeError("handler blew up"))
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()
        session.close.assert_awaited_once()


class TestAppWiring:
    def test_lifespan_attaches_engine_and_factory(self) -> None:
        from fastapi.testclient import TestClient

        app = create_app(make_settings())
        with TestClient(app):
            assert isinstance(app.state.engine, AsyncEngine)
            assert app.state.session_factory is not None
