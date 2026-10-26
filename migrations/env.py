"""Alembic environment, wired for the async engine.

The database URL comes from Settings, never from alembic.ini, so no
credential is ever committed.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

# Importing the models package registers every model on Base.metadata.
# Without it autogenerate sees an empty schema and proposes dropping
# everything. Populated from INS-5.
import insight.models
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from insight.config import get_settings
from insight.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        # Detect column type and server-default changes, not just added and
        # dropped columns. Without these, a varchar(50) -> varchar(200) or a
        # changed default is silently missed by autogenerate.
        compare_type=True,
        compare_server_default=True,
        # Every migration runs in one transaction; a failure half way leaves
        # the schema untouched rather than partly migrated.
        transaction_per_migration=False,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting - `alembic upgrade head --sql`."""
    _configure(
        url=get_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # NullPool: a migration run is a single short-lived connection, and
    # pooling would keep the process alive after it finishes.
    engine = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
