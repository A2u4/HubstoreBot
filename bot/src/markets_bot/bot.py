"""The bot client: wires settings, database, routing and feature cogs together."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

import discord
from discord.ext import commands

from markets_bot.core import command_sync
from markets_bot.core.audit import send_audit
from markets_bot.core.config import Settings
from markets_bot.core.db import Database
from markets_bot.core.dedupe import remove_duplicate_bot_output
from markets_bot.core.guild_config import GuildConfigService
from markets_bot.core.peers import PeerClient
from markets_bot.core.pipeline import MessagePipeline
from markets_bot.core.router import ComponentRouter
from markets_bot.core.tree import MarketsCommandTree
from markets_bot.web.internal_server import InternalServer

log = logging.getLogger(__name__)

# Feature modules, loaded in this order.
EXTENSIONS: tuple[str, ...] = (
    "markets_bot.cogs.dashboard_api",
    "markets_bot.cogs.server_logs",
    "markets_bot.cogs.members",
    "markets_bot.cogs.invites",
    "markets_bot.cogs.config",
    "markets_bot.cogs.moderation",
    "markets_bot.cogs.automod",
    "markets_bot.cogs.cluster_sync",
    "markets_bot.cogs.market_security",
    "markets_bot.cogs.tickets",
    "markets_bot.cogs.shop",
    "markets_bot.cogs.reputation",
    "markets_bot.cogs.giveaways",
    "markets_bot.cogs.rifas",
    "markets_bot.cogs.automation",
    "markets_bot.cogs.community",
    "markets_bot.cogs.sticky",
    "markets_bot.cogs.reaction_roles",
    "markets_bot.cogs.backups",
    "markets_bot.cogs.stats_channels",
    "markets_bot.cogs.utility",
    "markets_bot.cogs.staff_tools",
    "markets_bot.cogs.leveling",
    "markets_bot.cogs.economy",
    "markets_bot.cogs.social",
    "markets_bot.cogs.verification",
    "markets_bot.cogs.temp_voice",
)


def build_intents() -> discord.Intents:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True
    intents.guild_messages = True
    intents.guild_reactions = True
    intents.invites = True
    intents.presences = True
    intents.voice_states = True
    intents.moderation = True
    intents.message_content = True
    intents.dm_messages = True
    intents.emojis_and_stickers = True
    return intents


class MarketsBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=build_intents(),
            tree_cls=MarketsCommandTree,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=True),
            member_cache_flags=discord.MemberCacheFlags.all(),
            chunk_guilds_at_startup=True,
        )
        self.settings = settings
        self.db = Database(settings.database_url)
        self.configs = GuildConfigService(self.db)
        self.router = ComponentRouter()
        self.pipeline = MessagePipeline()
        self.peers = PeerClient(settings)
        self.internal = InternalServer(self)
        self._startup_synced = False
        self._background: set[asyncio.Task[Any]] = set()

    @property
    def identity(self) -> str:
        return self.settings.identity

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        for extension in EXTENSIONS:
            await self.load_extension(extension)
        log.info("Loaded %d feature modules", len(EXTENSIONS))
        if self.settings.internal_port:
            await self.internal.start(self.settings.internal_port)
        else:
            log.warning("[internal] %s_INTERNAL_PORT not set: peer sync and dashboard actions disabled",
                        self.identity.upper())

    async def on_ready(self) -> None:
        log.info("Logged in as %s, serving %d guilds", self.user, len(self.guilds))
        if not self._startup_synced:
            self._startup_synced = True
            self.spawn(self._initial_command_sync(), name="initial-command-sync")

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
        """Run a fire-and-forget task while keeping a reference so it isn't garbage collected."""
        task = asyncio.create_task(coro, name=name)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def _initial_command_sync(self) -> None:
        try:
            await command_sync.sync_all(self)
        except discord.HTTPException:
            log.exception("Startup command sync failed")

    async def close(self) -> None:
        await self.internal.stop()
        await self.peers.close()
        await super().close()
        await self.db.close()

    # ── Global event routing ─────────────────────────────────────────────

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type in (discord.InteractionType.component, discord.InteractionType.modal_submit):
            await self.router.dispatch(interaction)

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        if message.author.bot and await remove_duplicate_bot_output(message):
            return
        config = await self.configs.get(message.guild.id)
        await self.pipeline.run(message, config)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("Joined guild %s (%s) with %s members", guild.name, guild.id, guild.member_count)
        await self.configs.get(guild.id)
        try:
            await command_sync.sync_guild(self, guild.id)
        except discord.HTTPException as exc:
            log.error("Failed to deploy commands to new guild %s: %s", guild.id, exc)

    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: discord.app_commands.Command  # type: ignore[type-arg]
    ) -> None:
        """Every executed slash command is logged to the guild's audit channel."""
        if interaction.guild is None:
            return
        options = _format_options((interaction.data or {}).get("options", []))  # type: ignore[arg-type]
        embed = discord.Embed(color=0x5865F2, title="⌨️ Comando ejecutado", timestamp=discord.utils.utcnow())
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="📋 Comando", value=f"`/{command.qualified_name}`", inline=True)
        embed.add_field(name="👤 Usuario", value=interaction.user.mention, inline=True)
        embed.add_field(name="📢 Canal", value=f"<#{interaction.channel_id}>", inline=True)
        if options:
            embed.add_field(name="⚙️ Opciones", value=options[:1024], inline=False)
        embed.set_footer(text=f"ID: {interaction.user.id}")
        await send_audit(self, interaction.guild, embed)


def _format_options(options: list[dict[str, object]]) -> str:
    parts = []
    for option in options:
        if "options" in option:  # subcommand / group: flatten
            nested = _format_options(option["options"])  # type: ignore[arg-type]
            parts.append(f"{option['name']}: [subcomando]" + (f", {nested}" if nested else ""))
        else:
            parts.append(f"{option['name']}: {option.get('value')}")
    return ", ".join(parts)
