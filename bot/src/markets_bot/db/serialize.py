"""Model -> JSON-ready dict using the database (camelCase) column names.

Peer bots (including v1 TypeScript bots) and the dashboard expect Prisma's
field names, so rows cross process boundaries in this shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from markets_bot.db.base import Base


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds") + "Z"  # stored as naive UTC


def to_wire(row: Base) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in row.__table__.columns:  # type: ignore[attr-defined]
        attr = row.__mapper__.get_property_by_column(column).key  # type: ignore[attr-defined]
        value = getattr(row, attr)
        result[column.name] = _iso(value) if isinstance(value, datetime) else value
    return result
