"""Declarative base shared by every model.

The database schema is owned by Prisma (``prisma/schema.prisma``) because the
Next.js dashboard reads the same tables. Prisma keeps field names as camelCase
column names, so this base maps idiomatic snake_case attributes onto them:
``guild_id: Mapped[str] = mapped_column(String)`` becomes column ``"guildId"``.

Every column must be declared with ``mapped_column()`` for the rename to apply.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import DeclarativeBase, MappedColumn


def camel_case(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def new_id() -> str:
    """Prisma's ``@default(uuid())`` is generated client-side, so we do the same."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Prisma stores ``DateTime`` as naive UTC ``timestamp(3)``."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    def __init_subclass__(cls, **kwargs: Any) -> None:
        for key, value in list(cls.__dict__.items()):
            if isinstance(value, MappedColumn) and value.column.name is None:
                value.column.name = camel_case(key)
                value.column.key = camel_case(key)
        super().__init_subclass__(**kwargs)
