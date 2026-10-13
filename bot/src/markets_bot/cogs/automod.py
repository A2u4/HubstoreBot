"""AutoMod: anti-spam, anti-flood, anti-caps, anti-links and blacklisted words.

Runs first in the message pipeline; when it deletes a message the remaining
handlers are skipped.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from datetime import timedelta

import discord
from discord.ext import commands, tasks

from markets_bot.bot import MarketsBot
from markets_bot.core.audit import send_to
from markets_bot.core.pipeline import MessagePipeline
from markets_bot.core.tasks import resilient
from markets_bot.core.utils import PINK, truncate
from markets_bot.db.models import GuildConfig

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
WARNING_TTL_SECONDS = 5
FLOOD_SLOWMODE_SECONDS = 10
FLOOD_SLOWMODE_DURATION = 30


def caps_percent(text: str) -> float | None:
    letters = [c for c in text if c.isascii() and c.isalpha()]
    if not letters:
        return None
    return sum(1 for c in letters if c.isupper()) / len(letters) * 100


def blocked_url(content: str, whitelist: list[str]) -> str | None:
    """First URL not matching any whitelist entry, or None."""
    allowed = [w.lower() for w in whitelist]
    for url in URL_RE.findall(content):
        if not any(entry in url.lower() for entry in allowed):
            return url
    return None


class AutoMod(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self._user_messages: dict[str, deque[float]] = {}
        self._channel_messages: dict[int, deque[float]] = {}
        bot.pipeline.register("automod", self.handle, MessagePipeline.AUTOMOD)

    async def cog_load(self) -> None:
        self.cleanup_trackers.start()

    async def cog_unload(self) -> None:
        self.cleanup_trackers.cancel()
        self.bot.pipeline.unregister("automod")

    @tasks.loop(minutes=5)
    @resilient
    async def cleanup_trackers(self) -> None:
        cutoff = time.monotonic() - 60
        for store in (self._user_messages, self._channel_messages):
            for key in [k for k, stamps in store.items() if not stamps or stamps[-1] < cutoff]:
                del store[key]  # type: ignore[arg-type]

    async def _warn(self, message: discord.Message, text: str) -> None:
        try:
            await message.channel.send(text, delete_after=WARNING_TTL_SECONDS)
        except discord.HTTPException:
            pass

    async def _log(self, message: discord.Message, config: GuildConfig, kind: str, details: str) -> None:
        if message.guild is None:
            return
        embed = discord.Embed(color=PINK, title=f"AutoMod: {kind}", timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{message.author.name} ({message.author.mention})", inline=True)
        embed.add_field(name="Canal", value=f"<#{message.channel.id}>", inline=True)
        embed.add_field(name="Detalles", value=details, inline=False)
        embed.add_field(name="Mensaje", value=truncate(message.content, 512) or "*vacio*", inline=False)
        await send_to(message.guild, config.mod_log_channel_id, embed=embed)

    @staticmethod
    async def _delete(message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            pass

    @staticmethod
    def _hit(store: dict, key: object, window: float, threshold: int) -> bool:
        now = time.monotonic()
        stamps = store.setdefault(key, deque())
        while stamps and now - stamps[0] >= window:
            stamps.popleft()
        stamps.append(now)
        if len(stamps) >= threshold:
            store.pop(key, None)
            return True
        return False

    async def handle(self, message: discord.Message, config: GuildConfig) -> bool:
        if not config.automod_enabled or not isinstance(message.author, discord.Member):
            return False
        member = message.author
        exempt_roles = set(config.automod_exempt_role_ids or [])
        if exempt_roles and any(str(r.id) in exempt_roles for r in member.roles):
            return False
        if str(message.channel.id) in (config.automod_exempt_channel_ids or []):
            return False
        if message.channel.permissions_for(member).manage_messages:
            return False

        interval = config.anti_spam_interval or 5
        threshold = config.anti_spam_threshold or 5

        if config.anti_spam_enabled and self._hit(
            self._user_messages, f"{message.guild.id}:{member.id}", interval, threshold  # type: ignore[union-attr]
        ):
            await self._delete(message)
            await self._log(message, config, "Anti-Spam", f"Sent {threshold}+ messages in {interval}s")
            try:
                await member.timeout(timedelta(minutes=1), reason="Auto-mod: spam detected")
            except discord.HTTPException:
                pass
            return True

        if config.anti_flood_enabled and self._hit(self._channel_messages, message.channel.id, interval, threshold * 3):
            await self._log(message, config, "Anti-Flood", f"{threshold * 3}+ messages in {interval}s in channel")
            channel = message.channel
            if isinstance(channel, discord.TextChannel) and channel.slowmode_delay < FLOOD_SLOWMODE_SECONDS:
                previous = channel.slowmode_delay
                try:
                    await channel.edit(slowmode_delay=FLOOD_SLOWMODE_SECONDS, reason="Auto-mod: flood detected")
                    self.bot.spawn(self._restore_slowmode(channel, previous), name=f"flood-restore-{channel.id}")
                except discord.HTTPException:
                    pass
            return False

        content = message.content
        if config.anti_caps_enabled and len(content) > (config.anti_caps_min_length or 10):
            percent = caps_percent(content)
            limit = config.anti_caps_threshold or 70
            if percent is not None and percent >= limit:
                await self._delete(message)
                await self._log(message, config, "Anti-Caps", f"{round(percent)}% uppercase (threshold: {limit}%)")
                await self._warn(message, f"{member.mention}, por favor no uses mayusculas en exceso.")
                return True

        if config.anti_links_enabled:
            url = blocked_url(content, config.anti_links_whitelist or [])
            if url:
                await self._delete(message)
                await self._log(message, config, "Anti-Links", f"Blocked URL: {url}")
                await self._warn(message, f"{member.mention}, los enlaces no estan permitidos en este canal.")
                return True

        if config.blacklist_enabled and config.blacklisted_words:
            lowered = content.lower()
            word = next((w for w in config.blacklisted_words if w.lower() in lowered), None)
            if word:
                await self._delete(message)
                await self._log(message, config, "Blacklisted Word", f"Triggered: ||{word}||")
                await self._warn(message, f"{member.mention}, esa palabra no esta permitida aqui.")
                return True
        return False

    @staticmethod
    async def _restore_slowmode(channel: discord.TextChannel, previous: int) -> None:
        await asyncio.sleep(FLOOD_SLOWMODE_DURATION)
        try:
            await channel.edit(slowmode_delay=previous, reason="Auto-mod: flood cooldown expired")
        except discord.HTTPException:
            pass


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(AutoMod(bot))
