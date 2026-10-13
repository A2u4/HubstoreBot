"""Server stat channels: voice channels renamed with live counts (members, online, bots...)."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks
from sqlalchemy import select

from markets_bot.bot import MarketsBot
from markets_bot.core.tasks import resilient
from markets_bot.db.models import GuildConfig

log = logging.getLogger(__name__)


def stat_count(kind: str, guild: discord.Guild) -> int:
    members = guild.members  # full member cache (members intent + chunking at startup)
    match kind:
        case "members":
            return guild.member_count or len(members)
        case "humans":
            return sum(1 for m in members if not m.bot)
        case "bots":
            return sum(1 for m in members if m.bot)
        case "online":
            return sum(1 for m in members if not m.bot and m.status is not discord.Status.offline)
        case "roles":
            return len(guild.roles)
        case "channels":
            return len(guild.channels)
        case "boosts":
            return guild.premium_subscription_count or 0
    return 0


class StatsChannels(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.update_channels.start()

    async def cog_unload(self) -> None:
        self.update_channels.cancel()

    @tasks.loop(minutes=10)  # Discord allows ~2 channel renames per 10 minutes
    @resilient
    async def update_channels(self) -> None:
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(GuildConfig.id, GuildConfig.stats_channels).where(
                GuildConfig.id.in_(guild_ids)))).all()
        for guild_id, stats in rows:
            guild = self.bot.get_guild(int(guild_id))
            if guild is None or not isinstance(stats, list):
                continue
            for stat in stats:
                if not isinstance(stat, dict):
                    continue
                channel = guild.get_channel(int(stat.get("channelId") or 0))
                if channel is None:
                    continue
                name = str(stat.get("format") or "{count}").replace("{count}", str(stat_count(str(stat.get("type")), guild)), 1)
                if channel.name != name:
                    try:
                        await channel.edit(name=name[:100])
                    except discord.HTTPException as exc:
                        log.warning("Failed to update stats channel %s: %s", channel.id, exc)

    @update_channels.before_loop
    async def _wait(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(StatsChannels(bot))
