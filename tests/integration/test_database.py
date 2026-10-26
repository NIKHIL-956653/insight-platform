"""Integration tests against the real Postgres from infra/docker-compose.yml.

Excluded from a bare `pytest` run. To run them:

    docker compose --env-file .env -f infra/docker-compose.yml up -d
    pytest -m integration

These assert the things a unit test cannot: that the extensions the schema
depends on are actually installed, and that the server-side defaults the
models declare actually work on this server.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from insight.config import Settings, get_settings
from insight.db.session import create_audit_engine, create_engine

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_settings() -> Settings:
    """Real .env here - these tests are about the real database."""
    get_settings.cache_clear()
    return get_settings()


class TestConnection:
    async def test_application_role_can_connect(self, live_settings: Settings) -> None:
        engine = create_engine(live_settings)
        try:
            async with engine.connect() as conn:
                assert (await conn.scalar(text("SELECT 1"))) == 1
        finally:
            await engine.dispose()

    async def test_audit_role_can_connect(self, live_settings: Settings) -> None:
        engine = create_audit_engine(live_settings)
        try:
            async with engine.connect() as conn:
                who = await conn.scalar(text("SELECT current_user"))
                assert who == live_settings.postgres_audit_user
        finally:
            await engine.dispose()


class TestExtensions:
    async def test_pgvector_is_installed(self, live_settings: Settings) -> None:
        """Retrieval is dead without it, and the failure would surface as a
        confusing migration error rather than a clear one."""
        engine = create_engine(live_settings)
        try:
            async with engine.connect() as conn:
                version = await conn.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
            assert version is not None
        finally:
            await engine.dispose()

    async def test_server_side_uuid_generation_works(
        self, live_settings: Settings
    ) -> None:
        """UUIDPrimaryKeyMixin declares gen_random_uuid() as a server default."""
        engine = create_engine(live_settings)
        try:
            async with engine.connect() as conn:
                value = await conn.scalar(text("SELECT gen_random_uuid()"))
            parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
            assert parsed.version == 4
        finally:
            await engine.dispose()

    async def test_timestamps_are_timezone_aware_on_this_server(
        self, live_settings: Settings
    ) -> None:
        engine = create_engine(live_settings)
        try:
            async with engine.connect() as conn:
                now = await conn.scalar(text("SELECT now()"))
            assert now is not None
            assert now.tzinfo is not None
        finally:
            await engine.dispose()
