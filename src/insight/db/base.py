"""Declarative base, naming conventions and shared column mixins.

The naming convention is not cosmetic. Alembic's autogenerate compares
constraint names between the models and the live database; without a
convention, Postgres invents names like `documents_workspace_id_fkey1` and
autogenerate produces spurious drop/create pairs. It also means INS-8 can
refer to RLS policies and indexes by a name it can predict.

Changing the convention later renames every constraint in the database, so
it is fixed now, before the first migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class UUIDPrimaryKeyMixin:
    """UUIDv4 primary key.

    Not a serial integer. A sequential id leaks volume across tenants - a
    user in Workspace A seeing document 4,812 learns roughly how many
    documents the whole platform holds, and can probe for neighbours. On a
    multi-tenant system handling board material that is an information leak
    before it is an aesthetic choice.

    The server_default means rows created by a migration or by psql get an
    id too, not only rows created through the ORM.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """created_at / updated_at, both timezone-aware and set by the database.

    server_default rather than a Python default: the database clock is the
    one that matters, and it is the only clock a migration or a direct SQL
    insert will use.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
