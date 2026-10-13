"""Reputation: one ``reputations`` row is one +1 rep. Counts can be shared with peer bots."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from markets_bot.core.utils import utcnow
from markets_bot.db.base import new_id
from markets_bot.db.models import Reputation

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

SAME_GIVER_WINDOW = timedelta(seconds=10)
BATCH_SIZE = 1000
DEFAULT_MIGRATION_REASON = "migracion de reps"


class ReputationService:
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot

    async def grant_once(self, *, source: str, source_id: int | str, guild_id: int | str, user_id: int | str,
                         giver_id: int | str, reason: str | None) -> bool:
        """Insert one rep unless this source was already processed or the giver repped in the last 10s.

        The check and insert run in one SERIALIZABLE transaction; the deterministic
        row id (``rep-<source>-<sourceId>``) makes replays a no-op.
        """
        for attempt in range(4):
            try:
                async with self.bot.db.session(isolation_level="SERIALIZABLE") as session:
                    recent = await session.scalar(select(Reputation.id).where(
                        Reputation.guild_id == str(guild_id), Reputation.user_id == str(user_id),
                        Reputation.giver_id == str(giver_id),
                        Reputation.created_at >= utcnow() - SAME_GIVER_WINDOW).limit(1))
                    if recent:
                        return False
                    session.add(Reputation(id=f"rep-{source}-{source_id}", guild_id=str(guild_id),
                                           user_id=str(user_id), giver_id=str(giver_id), reason=reason))
                return True
            except IntegrityError:
                return False
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) == "40001" and attempt < 3:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise
        return False

    async def local_count(self, guild_id: int | str, user_id: int | str) -> int:
        async with self.bot.db.session() as session:
            return int(await session.scalar(select(func.count()).select_from(Reputation).where(
                Reputation.guild_id == str(guild_id), Reputation.user_id == str(user_id))) or 0)

    async def _linked_peers(self, guild_id: int | str) -> list:  # type: ignore[type-arg]
        config = await self.bot.configs.get(guild_id)
        peers = [self.bot.peers.find(gid) for gid in config.rep_sync_guild_ids or []]
        return [p for p in peers if p is not None]

    async def total(self, guild_id: int | str, user_id: int | str) -> int:
        """Local reps plus the reps of linked peer guilds (peers that fail count as 0)."""
        total = await self.local_count(guild_id, user_id)
        for peer in await self._linked_peers(guild_id):
            result = await self.bot.peers.call(peer, "reps/count", {"userId": str(user_id)})
            if result.ok and isinstance(result.data, dict):
                total += int(result.data.get("count") or 0)
            else:
                log.warning("Peer %s rep count failed: %s", peer.identity, result.error or result.status)
        return total

    async def leaderboard(self, guild_id: int | str, limit: int = 50) -> list[tuple[str, int]]:
        limit = min(max(limit, 1), 5000)
        counters: dict[str, int] = {}
        async with self.bot.db.session() as session:
            rows = (await session.execute(
                select(Reputation.user_id, func.count()).where(Reputation.guild_id == str(guild_id))
                .group_by(Reputation.user_id).order_by(func.count().desc()).limit(limit))).all()
        for uid, n in rows:
            counters[uid] = counters.get(uid, 0) + n
        for peer in await self._linked_peers(guild_id):
            result = await self.bot.peers.call(peer, "reps/leaderboard", {"limit": limit})
            if result.ok and isinstance(result.data, dict):
                for row in result.data.get("rows") or []:
                    if isinstance(row, dict) and isinstance(row.get("userId"), str):
                        counters[row["userId"]] = counters.get(row["userId"], 0) + max(0, int(row.get("count") or 0))
        return sorted(counters.items(), key=lambda item: item[1], reverse=True)[:limit]

    async def add(self, guild_id: int | str, user_id: int | str, giver_id: int | str, amount: int, reason: str) -> None:
        async with self.bot.db.session() as session:
            for start in range(0, amount, BATCH_SIZE):
                size = min(BATCH_SIZE, amount - start)
                now = utcnow()
                await session.execute(insert(Reputation), [
                    {"id": new_id(), "guild_id": str(guild_id), "user_id": str(user_id), "giver_id": str(giver_id),
                     "reason": reason, "created_at": now} for _ in range(size)])

    async def remove_recent(self, guild_id: int | str, user_id: int | str, amount: int) -> int:
        async with self.bot.db.session() as session:
            ids = (await session.execute(select(Reputation.id).where(
                Reputation.guild_id == str(guild_id), Reputation.user_id == str(user_id))
                .order_by(Reputation.created_at.desc()).limit(amount))).scalars().all()
            if ids:
                await session.execute(delete(Reputation).where(Reputation.id.in_(ids)))
        return len(ids)

    async def migrate(self, guild_id: int | str, from_user: int | str, to_user: int | str, reason: str) -> int:
        async with self.bot.db.session() as session:
            result = await session.execute(update(Reputation).where(
                Reputation.guild_id == str(guild_id), Reputation.user_id == str(from_user),
            ).values(user_id=str(to_user), reason=reason))
        moved = result.rowcount
        for peer in await self._linked_peers(guild_id):
            peer_result = await self.bot.peers.call(peer, "reps/migrate", {
                "fromUserId": str(from_user), "toUserId": str(to_user), "reason": reason, "fromGuildId": str(guild_id)})
            if peer_result.ok and isinstance(peer_result.data, dict):
                moved += int(peer_result.data.get("moved") or 0)
        return moved

    async def recent_received(self, guild_id: int | str, user_id: int | str, limit: int = 10) -> list[Reputation]:
        async with self.bot.db.session() as session:
            return list((await session.execute(select(Reputation).where(
                Reputation.guild_id == str(guild_id), Reputation.user_id == str(user_id))
                .order_by(Reputation.created_at.desc()).limit(limit))).scalars().all())
