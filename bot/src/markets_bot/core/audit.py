"""Audit / moderation log helpers shared by every module."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

import discord

from markets_bot.core.dedupe import claim_side_effect
from markets_bot.core.utils import ERROR, OK, WARN, is_snowflake

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

AUDIT_CHANNEL_NAME = "auditoria"
# Guilds whose audit channel predates the config field.
LEGACY_AUDIT_CHANNELS = {"1420045220325625898": "1420854487945445499"}


def text_channel(guild: discord.Guild, channel_id: str | int | None) -> discord.abc.Messageable | None:
    """Resolve a configured channel ID to something we can send to (or None)."""
    if not channel_id:
        return None
    try:
        channel = guild.get_channel_or_thread(int(channel_id))
    except (TypeError, ValueError):
        return None
    return channel if isinstance(channel, discord.abc.Messageable) else None


async def send_to(
    guild: discord.Guild, channel_id: str | int | None, **kwargs: object
) -> discord.Message | None:
    """Send to a configured channel, swallowing missing-channel / permission errors."""
    channel = text_channel(guild, channel_id)
    if channel is None:
        return None
    try:
        return await channel.send(**kwargs)  # type: ignore[arg-type]
    except discord.HTTPException as exc:
        log.debug("Could not send to channel %s: %s", channel_id, exc)
        return None


async def _resolve_audit_channel(
    bot: MarketsBot, guild: discord.Guild, fallback_channel_id: str | None
) -> discord.TextChannel | None:
    config = await bot.configs.get(guild.id)
    configured_id = config.audit_log_channel_id or fallback_channel_id or LEGACY_AUDIT_CHANNELS.get(str(guild.id))
    configured = text_channel(guild, configured_id)
    if isinstance(configured, discord.TextChannel):
        return configured

    existing = discord.utils.find(
        lambda c: c.name.lower() == AUDIT_CHANNEL_NAME, guild.text_channels
    )
    if existing:
        return existing
    if not guild.me.guild_permissions.manage_channels:
        return None
    try:
        return await guild.create_text_channel(AUDIT_CHANNEL_NAME, reason="Canal de auditoria del bot")
    except discord.HTTPException as exc:
        log.warning("Could not create #%s in %s: %s", AUDIT_CHANNEL_NAME, guild.name, exc)
        return None


async def send_audit(
    bot: MarketsBot,
    guild: discord.Guild,
    embed: discord.Embed,
    *,
    fallback_channel_id: str | None = None,
    already_sent: Iterable[int | str | None] = (),
) -> None:
    """Post ``embed`` to the guild's audit channel (creating ``#auditoria`` if needed)."""
    signature = f"{guild.id}:{embed.title or ''}:{embed.footer.text or ''}:{(embed.description or '')[:160]}"
    if not claim_side_effect(f"audit:{signature}"):
        return
    try:
        channel = await _resolve_audit_channel(bot, guild, fallback_channel_id)
        if channel is None or any(str(cid) == str(channel.id) for cid in already_sent if cid):
            return
        await channel.send(embed=embed)
    except discord.HTTPException as exc:
        log.error("Failed to send audit log in %s: %s", guild.id, exc)


async def audit_executor(guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None) -> str:
    """Who performed ``action`` on ``target_id`` in the last 15 seconds (mention or 'Desconocido')."""
    try:
        cutoff = discord.utils.utcnow() - timedelta(seconds=15)
        async for entry in guild.audit_logs(action=action, limit=5):
            target = getattr(entry.target, "id", None)
            if entry.created_at >= cutoff and (target_id is None or target == target_id) and entry.user:
                return f"<@{entry.user.id}> (`{entry.user.id}`)"
    except discord.HTTPException:
        pass
    return "Desconocido"


def truncate_audit_value(value: str | None, limit: int = 900) -> str:
    text = (value or "").strip() or "*Ninguno*"
    return text if len(text) <= limit else text[: limit - 3] + "..."


# ─── Moderation embeds ───────────────────────────────────────────────────────

ModKind = Literal["ban", "unban", "kick", "warn", "mute", "unmute"]

_MOD_META: dict[str, tuple[int, str, str, str]] = {
    "ban": (ERROR, "🚨", "USUARIO BANEADO", "baneado permanentemente"),
    "unban": (OK, "✅", "Usuario desbaneado", "desbaneado"),
    "kick": (0xED7D31, "👢", "Usuario expulsado", "expulsado"),
    "warn": (WARN, "⚠️", "Advertencia", "advertido"),
    "mute": (0x95A5A6, "🔇", "Usuario silenciado", "silenciado"),
    "unmute": (OK, "🔊", "Silencio removido", "desilenciado"),
}


def mod_embed(
    kind: ModKind,
    guild: discord.Guild,
    target: discord.abc.User | discord.Object,
    moderator_id: str | int | None,
    moderator_name: str = "Desconocido",
    *,
    reason: str | None = None,
    duration: str | None = None,
    origin_guild_name: str | None = None,
    extra: list[tuple[str, str, bool]] | None = None,
) -> discord.Embed:
    """Unified embed for ban / kick / warn / mute actions (also used by ban sync)."""
    color, icon, title, verb = _MOD_META[kind]
    target_name = getattr(target, "name", None) or str(target.id)
    embed = discord.Embed(
        color=color,
        title=f"{icon} {title}",
        description=f"**{target_name}** ha sido {verb}.",
        timestamp=discord.utils.utcnow(),
    )
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    moderator = str(moderator_id) if moderator_id else ""
    embed.add_field(name="Servidor", value=origin_guild_name or guild.name, inline=True)
    embed.add_field(name="Usuario", value=f"<@{target.id}>", inline=True)
    embed.add_field(
        name="Moderador", value=f"<@{moderator}>" if is_snowflake(moderator) else moderator_name, inline=True
    )
    if duration:
        embed.add_field(name="Duración", value=duration, inline=True)
    embed.add_field(name="Razón", value=reason or "Sin razón especificada", inline=False)
    for name, value, inline in extra or []:
        embed.add_field(name=name, value=value, inline=inline)
    embed.set_footer(text=f"ID: {target.id}")
    avatar = getattr(target, "display_avatar", None)
    if avatar:
        embed.set_thumbnail(url=avatar.url)
    return embed


async def send_mod_log(bot: MarketsBot, guild: discord.Guild, embed: discord.Embed) -> None:
    config = await bot.configs.get(guild.id)
    await send_to(guild, config.mod_log_channel_id, embed=embed)
