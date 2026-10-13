"""Pure helpers shared by every module (no Discord or database access)."""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import TypeVar

T = TypeVar("T")

# ─── Colors ──────────────────────────────────────────────────────────────────

OK = 0x57F287
ERROR = 0xED4245
INFO = 0x5865F2
WARN = 0xFEE75C
MUTED = 0x99AAB5
PINK = 0xEB459E
ORANGE = 0xF47B67

_MODULE_COLORS = {
    "invites": 0x5865F2,
    "backup": 0x57F287,
    "moderation": 0xED4245,
    "automod": 0xEB459E,
    "automation": 0xF47B67,
    "tickets": 0x5865F2,
    "config": 0x99AAB5,
    "reputation": 0x57F287,
    "giveaway": 0xF47B67,
    "suggestions": 0x3498DB,
    "starboard": 0xFEE75C,
    "utility": 0x99AAB5,
    "afk": 0x99AAB5,
    "leveling": 0x5865F2,
    "economy": 0xF1C40F,
    "fun": 0xEB459E,
}

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def module_color(module: str) -> int:
    return _MODULE_COLORS.get(module, INFO)


def parse_color(value: str | None, default: int = INFO) -> int:
    """``"#5865F2"`` / ``"5865f2"`` -> int; anything invalid -> ``default``."""
    if not value:
        return default
    match = _HEX_RE.match(value.strip())
    return int(match.group(1), 16) if match else default


# ─── Durations ───────────────────────────────────────────────────────────────

_DURATION_RE = re.compile(r"(\d+)\s*(s|sec|m|min|h|hr|hour|d|day|w|week)", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str | None) -> int | None:
    """``"1d2h30m"`` -> seconds. Returns None when nothing parseable is found."""
    if not text:
        return None
    total = sum(int(value) * _UNIT_SECONDS[unit[0].lower()] for value, unit in _DURATION_RE.findall(text))
    return total or None


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    parts = []
    for suffix, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount}{suffix}")
    return " ".join(parts) or "0s"


# ─── Text ────────────────────────────────────────────────────────────────────


def render_template(template: str, variables: dict[str, str]) -> str:
    """Replace ``{name}`` placeholders. Unknown placeholders are left untouched."""
    result = template
    for key, value in variables.items():
        result = result.replace("{" + key + "}", value)
    return result


def truncate(text: str | None, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def chunks[T](items: Sequence[T], size: int) -> Iterable[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


# ─── Time ────────────────────────────────────────────────────────────────────


def utcnow() -> datetime:
    """Naive UTC, matching how Prisma stores ``DateTime``."""
    return datetime.now(UTC).replace(tzinfo=None)


def aware(moment: datetime) -> datetime:
    """Database datetimes are naive UTC; Discord embeds need timezone-aware values."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def discord_ts(moment: datetime, style: str = "R") -> str:
    """Discord timestamp markup. Naive datetimes are treated as UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return f"<t:{int(moment.timestamp())}:{style}>"


# ─── Randomness ──────────────────────────────────────────────────────────────


def crypto_sample[T](items: Sequence[T], count: int) -> list[T]:
    """Fair, CSPRNG-backed sample (giveaway winners, raffle draws)."""
    pool = list(items)
    k = min(max(count, 0), len(pool))
    for i in range(k):
        j = i + secrets.randbelow(len(pool) - i)
        pool[i], pool[j] = pool[j], pool[i]
    return pool[:k]


SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")


def is_snowflake(value: str | None) -> bool:
    return bool(value and SNOWFLAKE_RE.match(value))


def mention_or_text(user_id: str) -> str:
    return f"<@{user_id}>" if is_snowflake(user_id) else user_id
