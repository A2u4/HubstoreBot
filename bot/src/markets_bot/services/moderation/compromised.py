"""Cleanup for a hacked account (``/hackeado``).

1. Timeout the member so it can't keep posting.
2. Delete its recent messages in every text / announcement / voice chat / thread,
   paging back through history (not only the last 100 messages).
3. Revoke invites the account created.
4. DM the owner how to secure the account.
5. Log with a sample of what was removed; staff get a "release" button.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord

from markets_bot.core.audit import send_audit
from markets_bot.core.utils import OK
from markets_bot.services.moderation import invite_revocation

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

TWO_WEEKS = timedelta(days=14)
MAX_PAGES_PER_CHANNEL = 10
CHANNEL_CONCURRENCY = 3
RELEASE_PREFIX = "hack_release_"
_URL_RE = re.compile(r"https?://\S+")

MessageChannel = discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread


@dataclass(slots=True)
class CleanupResult:
    timeout_ok: bool = False
    timeout_error: str | None = None
    deleted: int = 0
    channels: list[tuple[int, int]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    invites_revoked: int = 0
    dm_sent: bool = False


async def _channels(guild: discord.Guild) -> list[MessageChannel]:
    channels: list[MessageChannel] = [
        c for c in guild.channels
        if isinstance(c, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel))
    ]
    try:
        threads = await guild.active_threads()
    except discord.HTTPException:
        threads = list(guild.threads)
    channels.extend(t for t in threads if t not in channels)
    me = guild.me
    usable = []
    for channel in channels:
        perms = channel.permissions_for(me)
        if perms.view_channel and perms.read_message_history and perms.manage_messages:
            usable.append(channel)
    return usable


async def _find_messages(channel: MessageChannel, user_id: int, since: datetime) -> list[discord.Message]:
    found: list[discord.Message] = []
    before: discord.Message | None = None
    for _ in range(MAX_PAGES_PER_CHANNEL):
        batch = [m async for m in channel.history(limit=100, before=before)]
        if not batch:
            break
        reached_old = False
        for message in batch:
            if message.created_at < since:
                reached_old = True
                continue
            if message.author.id == user_id and not message.pinned:
                found.append(message)
        before = min(batch, key=lambda m: m.created_at)
        if reached_old or len(batch) < 100:
            break
    return found


async def _delete(channel: MessageChannel, messages: list[discord.Message]) -> int:
    deleted = 0
    cutoff = discord.utils.utcnow() - TWO_WEEKS + timedelta(minutes=1)
    bulkable = [m for m in messages if m.created_at > cutoff]
    single = [m for m in messages if m.created_at <= cutoff]
    for i in range(0, len(bulkable), 100):
        chunk = bulkable[i:i + 100]
        if len(chunk) >= 2:
            try:
                await channel.delete_messages(chunk)
                deleted += len(chunk)
                continue
            except discord.HTTPException:
                pass
        single.extend(chunk)
    for message in single:
        try:
            await message.delete()
            deleted += 1
        except discord.HTTPException:
            pass
        await asyncio.sleep(0.12)
    return deleted


def _describe(message: discord.Message) -> str:
    text = " ".join(message.content.split())[:120]
    files = len(message.attachments)
    files_text = f" [{files} archivo{'' if files == 1 else 's'}]" if files else ""
    links = len(_URL_RE.findall(message.content))
    links_text = f" [{links} enlace(s)]" if links and "http" not in text else ""
    return f"<#{message.channel.id}> {f'“{text}”' if text else '*sin texto*'}{files_text}{links_text}"


async def cleanup(
    guild: discord.Guild, target: discord.User, *, messages_since: timedelta, timeout: timedelta,
    reason: str, revoke_invites: bool, notify_user: bool,
) -> CleanupResult:
    result = CleanupResult()
    try:
        member = await guild.fetch_member(target.id)
    except discord.HTTPException:
        member = None
    if member is None:
        result.timeout_error = "El usuario no está en el servidor."
    elif member.top_role >= guild.me.top_role or member.id == guild.owner_id:
        result.timeout_error = "No puedo aislarlo (tiene un rol igual o superior al del bot)."
    else:
        try:
            await member.timeout(timeout, reason=reason)
            result.timeout_ok = True
        except discord.HTTPException as exc:
            result.timeout_error = str(exc) or "Error desconocido."

    since = max(discord.utils.utcnow() - messages_since, discord.utils.utcnow() - TWO_WEEKS)
    channels = await _channels(guild)
    semaphore = asyncio.Semaphore(CHANNEL_CONCURRENCY)

    async def process(channel: MessageChannel) -> None:
        async with semaphore:
            try:
                messages = await _find_messages(channel, target.id, since)
                if not messages:
                    return
                for message in messages:
                    if len(result.evidence) < 6:
                        result.evidence.append(_describe(message))
                count = await _delete(channel, messages)
                if count:
                    result.deleted += count
                    result.channels.append((channel.id, count))
            except discord.HTTPException as exc:
                log.warning("[Hackeado] Cleanup failed in %s: %s", channel.id, exc)

    await asyncio.gather(*(process(c) for c in channels))
    result.channels.sort(key=lambda item: item[1], reverse=True)

    if revoke_invites:
        try:
            revoked = await invite_revocation.revoke_for_users(guild, [target.id], f"Cuenta comprometida: {target.name}")
            result.invites_revoked = revoked.revoked
        except discord.HTTPException:
            pass

    if notify_user:
        embed = discord.Embed(color=0xED4245, title="Tu cuenta parece estar comprometida", description="\n".join([
            f"El staff de **{guild.name}** detectó mensajes sospechosos desde tu cuenta y la aisló temporalmente "
            "para proteger a otros miembros.",
            "",
            "**Para recuperarla:**",
            "1. Cambia tu contraseña de Discord (esto cierra las demás sesiones).",
            "2. Activa la verificación en dos pasos (2FA).",
            "3. Ajustes → Dispositivos: cierra las sesiones que no reconozcas.",
            "4. Ajustes → Aplicaciones autorizadas: elimina las que no conozcas.",
            "5. No escanees códigos QR ni ejecutes archivos que te envíen.",
            "",
            "Cuando la recuperes, avisa al staff para quitar el aislamiento.",
        ]))
        try:
            await target.send(embed=embed)
            result.dm_sent = True
        except discord.HTTPException:
            result.dm_sent = False
    return result


def release_view(user_id: int, disabled: bool = False) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        custom_id=f"{RELEASE_PREFIX}{user_id}", emoji="🔓", style=discord.ButtonStyle.success, disabled=disabled,
        label="Aislamiento retirado" if disabled else "Quitar aislamiento (cuenta recuperada)",
    ))
    return view


def cleanup_embed(target: discord.User, moderator_id: int, result: CleanupResult, *, messages: str, timeout: str,
                  reason: str) -> discord.Embed:
    embed = discord.Embed(color=0xFFA500, title="⚠️ Cuenta comprometida — acciones aplicadas",
                          timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=target.display_avatar.with_size(256).url)
    embed.add_field(name="👤 Usuario", value=f"{target.mention}\n`{target.name}` · `{target.id}`", inline=True)
    embed.add_field(name="🛡️ Moderador", value=f"<@{moderator_id}>", inline=True)
    embed.add_field(name="⏳ Aislamiento", value=f"✅ {timeout}" if result.timeout_ok else f"❌ {result.timeout_error}",
                    inline=True)
    embed.add_field(name="🗑️ Mensajes borrados",
                    value=f"**{result.deleted}** (últimos {messages}) en **{len(result.channels)}** canal(es)", inline=True)
    embed.add_field(name="🔗 Invitaciones revocadas", value=str(result.invites_revoked), inline=True)
    embed.add_field(name="✉️ Aviso al usuario",
                    value="Enviado por MD" if result.dm_sent else "No se pudo enviar (MD cerrados)", inline=True)
    embed.add_field(name="📋 Razón", value=reason[:1024], inline=False)
    embed.set_footer(text=f"ID: {target.id}")
    if result.channels:
        embed.add_field(name="📁 Canales", inline=False,
                        value="\n".join(f"<#{cid}>: **{n}**" for cid, n in result.channels)[:1024])
    if result.evidence:
        embed.add_field(name="🧾 Muestra de lo borrado", value="\n".join(result.evidence)[:1024], inline=False)
    return embed


async def log_cleanup(bot: MarketsBot, guild: discord.Guild, embed: discord.Embed) -> None:
    config = await bot.configs.get(guild.id)
    await send_audit(bot, guild, embed, fallback_channel_id=config.mod_log_channel_id or config.audit_log_channel_id)


async def handle_release(bot: MarketsBot, interaction: discord.Interaction) -> None:
    guild = interaction.guild
    if guild is None or not interaction.permissions.moderate_members:
        await interaction.response.send_message("Necesitas el permiso **Aislar miembros** para hacer esto.", ephemeral=True)
        return
    user_id = int(str((interaction.data or {}).get("custom_id", "")).removeprefix(RELEASE_PREFIX))
    try:
        member = await guild.fetch_member(user_id)
    except discord.HTTPException:
        await interaction.response.send_message("El usuario ya no está en el servidor.", ephemeral=True)
        return
    try:
        await member.timeout(None, reason=f"Cuenta recuperada · aislamiento retirado por {interaction.user.name}")
    except discord.HTTPException:
        await interaction.response.send_message("❌ No pude quitar el aislamiento (permisos o jerarquía).", ephemeral=True)
        return
    await interaction.response.edit_message(view=release_view(user_id, disabled=True))
    await interaction.followup.send(f"🔓 Aislamiento retirado a <@{user_id}>.", ephemeral=True)
    embed = discord.Embed(color=OK, title="🔓 Cuenta recuperada — aislamiento retirado", timestamp=discord.utils.utcnow())
    embed.add_field(name="Usuario", value=f"<@{user_id}> `{member.name}`", inline=True)
    embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
    embed.set_footer(text=f"ID: {user_id}")
    await log_cleanup(bot, guild, embed)
