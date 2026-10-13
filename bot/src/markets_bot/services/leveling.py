"""XP curve and persistence for the leveling module (MEE6-compatible curve)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from markets_bot.core.db import Database
from markets_bot.core.utils import utcnow
from markets_bot.db.base import new_id
from markets_bot.db.models import MemberLevel

MAX_LEVEL = 500


def xp_to_next(level: int) -> int:
    """XP needed to go from ``level`` to ``level + 1``."""
    return 5 * level * level + 50 * level + 100


@lru_cache(maxsize=MAX_LEVEL + 1)
def total_xp_for(level: int) -> int:
    """Total XP required to reach ``level`` from zero."""
    return 0 if level <= 0 else total_xp_for(level - 1) + xp_to_next(level - 1)


def level_from_xp(xp: int) -> int:
    level = 0
    while level < MAX_LEVEL and xp >= total_xp_for(level + 1):
        level += 1
    return level


@dataclass(slots=True)
class Progress:
    xp: int
    level: int
    current: int  # XP into the current level
    needed: int  # XP the current level requires

    @classmethod
    def of(cls, xp: int) -> Progress:
        level = level_from_xp(xp)
        return cls(xp=xp, level=level, current=xp - total_xp_for(level), needed=xp_to_next(level))


class LevelService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add_message_xp(self, guild_id: str, user_id: str, low: int, high: int) -> tuple[int, int, int] | None:
        """Grant random XP for one message. Returns ``(old_level, new_level, xp)`` when the level went up."""
        gain = random.randint(min(low, high), max(low, high))
        return await self.add_xp(guild_id, user_id, gain, count_message=True)

    async def add_xp(self, guild_id: str, user_id: str, amount: int, *,
                     count_message: bool = False) -> tuple[int, int, int] | None:
        now = utcnow()
        async with self.db.session() as session:
            row = (await session.execute(
                insert(MemberLevel).values(id=new_id(), guild_id=guild_id, user_id=user_id, xp=max(0, amount),
                                           level=0, messages=int(count_message), last_xp_at=now, updated_at=now)
                .on_conflict_do_update(index_elements=["guildId", "userId"], set_={
                    "xp": func.greatest(0, MemberLevel.xp + amount),
                    "messages": MemberLevel.messages + int(count_message),
                    "lastXpAt": now, "updatedAt": now})
                .returning(MemberLevel.xp, MemberLevel.level))).one()
            xp, stored = int(row.xp), int(row.level)
            new_level = level_from_xp(xp)
            if new_level == stored:
                return None
            # Conditional update: two racing messages can't announce the same level twice.
            changed = await session.scalar(
                update(MemberLevel).where(MemberLevel.guild_id == guild_id, MemberLevel.user_id == user_id,
                                          MemberLevel.level == stored)
                .values(level=new_level).returning(MemberLevel.id))
            return (stored, new_level, xp) if changed else None

    async def set_xp(self, guild_id: str, user_id: str, xp: int) -> int:
        xp = max(0, xp)
        level = level_from_xp(xp)
        async with self.db.session() as session:
            await session.execute(
                insert(MemberLevel).values(id=new_id(), guild_id=guild_id, user_id=user_id, xp=xp, level=level)
                .on_conflict_do_update(index_elements=["guildId", "userId"],
                                       set_={"xp": xp, "level": level, "updatedAt": utcnow()}))
        return level

    async def get(self, guild_id: str, user_id: str) -> MemberLevel | None:
        async with self.db.session() as session:
            return (await session.execute(select(MemberLevel).where(
                MemberLevel.guild_id == guild_id, MemberLevel.user_id == user_id))).scalar_one_or_none()

    async def rank(self, guild_id: str, xp: int) -> int:
        async with self.db.session() as session:
            above = await session.scalar(select(func.count()).select_from(MemberLevel).where(
                MemberLevel.guild_id == guild_id, MemberLevel.xp > xp))
        return int(above or 0) + 1

    async def leaderboard(self, guild_id: str, offset: int, limit: int) -> tuple[list[MemberLevel], int]:
        async with self.db.session() as session:
            total = await session.scalar(select(func.count()).select_from(MemberLevel).where(
                MemberLevel.guild_id == guild_id, MemberLevel.xp > 0))
            rows = (await session.execute(select(MemberLevel).where(MemberLevel.guild_id == guild_id, MemberLevel.xp > 0)
                                          .order_by(MemberLevel.xp.desc()).offset(offset).limit(limit))).scalars().all()
        return list(rows), int(total or 0)
