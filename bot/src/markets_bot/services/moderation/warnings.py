"""Warning helpers: synced warnings exist as an original row plus a mirrored row."""

from __future__ import annotations

from datetime import datetime
from typing import Any

WarningRow = dict[str, Any]


def _timestamp(row: WarningRow) -> float:
    value = row.get("createdAt")
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def canonical_id(row: WarningRow) -> str:
    return str(row.get("sourceWarningId") or row["id"])


def unique_warnings(rows: list[WarningRow]) -> list[WarningRow]:
    """Collapse original + mirrored copies into one logical warning, newest first."""
    unique: dict[str, WarningRow] = {}
    for row in sorted(rows, key=_timestamp, reverse=True):
        key = canonical_id(row)
        if key not in unique or _timestamp(row) > _timestamp(unique[key]):
            unique[key] = row
    return sorted(unique.values(), key=_timestamp, reverse=True)


def select_recent(rows: list[WarningRow], amount: int) -> list[WarningRow]:
    return unique_warnings(rows)[:amount] if amount >= 1 else []


def row_timestamp(row: WarningRow) -> float:
    return _timestamp(row)
