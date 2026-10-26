"""Async engine and session wiring.

Nothing is created at import time. The engine is built in the application
lifespan and stored on app.state, so tests can build their own against a
different database and a stray `import insight.db.session` never opens a
connection pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from insight.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine for the application role."""
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=settings.db_pool_pre_ping,
        # Recycle below typical idle timeouts on managed Postgres so a
        # connection is never handed out after the server has dropped it.
        pool_recycle=1800,
    )


def create_audit_engine(settings: Settings) -> AsyncEngine:
    """Engine for the INSERT-only audit role (INS-11).

    Deliberately separate. The audit chain is only tamper-evident if the
    writes go through a role that cannot UPDATE or DELETE, and that means a
    second connection pool, not a second schema on the same credentials.
    """
    return create_async_engine(
        settings.audit_database_url,
        echo=settings.db_echo,
        pool_size=max(2, settings.db_pool_size // 2),
        max_overflow=0,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_recycle=1800,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory.

    expire_on_commit=False so attributes stay readable after commit; the
    alternative is a surprise lazy-load on an already-closed async session,
    which raises rather than silently refetching.
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session scoped to one request.

    Commits on success, rolls back on any exception. Handlers should not
    commit themselves - one transaction per request keeps a half-applied
    write from ever reaching the database.

    INS-8 wraps this to set the tenant context for RLS.
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine(engine: AsyncEngine) -> None:
    """Close every pooled connection. Called from the lifespan shutdown."""
    await engine.dispose()
