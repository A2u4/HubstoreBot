"""Cached access to ``GuildConfig`` rows.

Configs are cached for 60 seconds. The dashboard calls the internal
``/internal/cache/invalidate`` endpoint after saving so edits apply instantly.
Returned objects are detached snapshots: change them through :meth:`update`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from markets_bot.core.cache import TtlCache
from markets_bot.core.db import Database
from markets_bot.db.models import GuildConfig

# Module name -> GuildConfig toggle attribute. "config" is always enabled.
MODULE_TOGGLES: dict[str, str] = {
    "invites": "invites_enabled",
    "moderation": "moderation_enabled",
    "automod": "automod_enabled",
    "tickets": "tickets_enabled",
    "automation": "automation_enabled",
    "welcome": "welcome_enabled",
    "farewell": "farewell_enabled",
    "reputation": "reputation_enabled",
    "giveaway": "giveaway_enabled",
    "rifa": "rifa_enabled",
    "suggestions": "suggestions_enabled",
    "starboard": "starboard_enabled",
    "afk": "afk_enabled",
    "backup": "backup_enabled",
    "sticky": "sticky_enabled",
    "logging": "logging_enabled",
    "leveling": "leveling_enabled",
    "economy": "economy_enabled",
    "fun": "fun_enabled",
    "verification": "verification_enabled",
    "tempvoice": "temp_voice_enabled",
}


class GuildConfigService:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: TtlCache[GuildConfig] = TtlCache(60, 500)

    async def get(self, guild_id: int | str) -> GuildConfig:
        key = str(guild_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        async with self._db.session() as session:
            await session.execute(insert(GuildConfig).values(id=key).on_conflict_do_nothing())
            config = (await session.execute(select(GuildConfig).where(GuildConfig.id == key))).scalar_one()
        self._cache.set(key, config)
        return config

    async def update(self, guild_id: int | str, **values: Any) -> GuildConfig:
        key = str(guild_id)
        await self.get(key)  # make sure the row exists
        async with self._db.session() as session:
            await session.execute(update(GuildConfig).where(GuildConfig.id == key).values(**values))
        self._cache.delete(key)
        return await self.get(key)

    def invalidate(self, guild_id: int | str | None = None) -> None:
        if guild_id is None:
            self._cache.clear()
        else:
            self._cache.delete(str(guild_id))

    @staticmethod
    def module_enabled(config: GuildConfig, module: str) -> bool:
        attr = MODULE_TOGGLES.get(module)
        return True if attr is None else bool(getattr(config, attr))
