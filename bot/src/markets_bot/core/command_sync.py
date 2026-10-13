"""Per-guild slash command deployment.

Commands are deployed as *guild* commands (instant updates) instead of global
ones. Each guild gets its own list: optional modules can hide commands, and
custom text commands created from the dashboard / ``/crear-texto`` are added.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from sqlalchemy import select

from markets_bot.core.tree import command_extras
from markets_bot.core.utils import parse_color
from markets_bot.db.models import CustomTextCommand

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

CUSTOM_TEXT_DESCRIPTION = "Comando de texto personalizado"


def _hidden_for_guild(command: app_commands.Command[Any, ..., Any] | app_commands.Group, config: Any) -> bool:
    module = command_extras(command).get("module")
    if module == "invites" and not config.invites_enabled:
        return True
    return command.name == "verificar" and not config.market_verification_enabled


def _custom_callback(bot: MarketsBot, name: str):  # type: ignore[no-untyped-def]
    async def callback(interaction: discord.Interaction) -> None:
        async with bot.db.session() as session:
            row = (
                await session.execute(
                    select(CustomTextCommand).where(
                        CustomTextCommand.guild_id == str(interaction.guild_id), CustomTextCommand.name == name
                    )
                )
            ).scalar_one_or_none()
        if row is None or not row.enabled:
            await interaction.response.send_message("Este comando ya no existe.", ephemeral=True)
            return
        embed = discord.Embed(
            color=parse_color(row.embed_color, 0xFFFFFF), description=row.text, timestamp=discord.utils.utcnow()
        )
        if row.show_author and interaction.guild:
            icon = interaction.guild.icon.with_size(128).url if interaction.guild.icon else None
            embed.set_author(name=interaction.guild.name, icon_url=icon)
        if row.title:
            embed.title = row.title
        if row.thumbnail_url:
            embed.set_thumbnail(url=row.thumbnail_url)
        await interaction.response.send_message(embed=embed)

    return callback


async def build_guild_payload(bot: MarketsBot, guild_id: int) -> list[dict[str, Any]]:
    config = await bot.configs.get(guild_id)
    guild_obj = discord.Object(guild_id)
    payload: list[dict[str, Any]] = []
    seen: set[str] = set()

    for command in bot.tree.get_commands(type=discord.AppCommandType.chat_input):
        if _hidden_for_guild(command, config) or command.name in seen:
            continue
        seen.add(command.name)
        payload.append(command.to_dict(bot.tree))
    for menu in bot.tree.get_commands(type=discord.AppCommandType.user):
        payload.append(menu.to_dict(bot.tree))
    for menu in bot.tree.get_commands(type=discord.AppCommandType.message):
        payload.append(menu.to_dict(bot.tree))

    async with bot.db.session() as session:
        customs = (
            await session.execute(
                select(CustomTextCommand)
                .where(CustomTextCommand.guild_id == str(guild_id), CustomTextCommand.enabled.is_(True))
                .order_by(CustomTextCommand.name)
            )
        ).scalars().all()

    bot.tree.clear_commands(guild=guild_obj)
    for custom in customs:
        if custom.name in seen:
            log.warning("Skipping custom text command /%s: a built-in command uses that name", custom.name)
            continue
        seen.add(custom.name)
        command = app_commands.Command(
            name=custom.name, description=CUSTOM_TEXT_DESCRIPTION, callback=_custom_callback(bot, custom.name)
        )
        bot.tree.add_command(command, guild=guild_obj, override=True)
        payload.append({"name": custom.name, "description": CUSTOM_TEXT_DESCRIPTION, "type": 1})
    return payload


async def sync_guild(bot: MarketsBot, guild_id: int) -> int:
    payload = await build_guild_payload(bot, guild_id)
    await bot.http.bulk_upsert_guild_commands(bot.application_id, guild_id, payload)  # type: ignore[arg-type]
    log.info("Deployed %d commands to guild %s", len(payload), guild_id)
    return len(payload)


async def sync_all(bot: MarketsBot) -> None:
    """Deploy to every guild, then clear global commands to avoid duplicates."""
    for guild in bot.guilds:
        try:
            await sync_guild(bot, guild.id)
        except discord.HTTPException as exc:
            log.error("Failed to deploy commands to %s: %s", guild.id, exc)
    if bot.guilds:
        await bot.http.bulk_upsert_global_commands(bot.application_id, [])  # type: ignore[arg-type]
        log.info("Cleared global commands to avoid guild/global duplicates")
