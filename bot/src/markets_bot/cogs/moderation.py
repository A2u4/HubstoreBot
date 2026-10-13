"""Moderation: /mod, /ban, /limpiar, /purgar, /modolento, /rol, /hackeado, /revocar-invitaciones.

Warnings and moderation history are shared with the linked peer bot
(Vapiano ↔ Hub Store) over the internal API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from datetime import timedelta
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import delete, or_, select, update

from markets_bot.bot import MarketsBot
from markets_bot.core.audit import mod_embed, send_mod_log, send_to
from markets_bot.core.tasks import resilient
from markets_bot.core.utils import (
    ERROR,
    OK,
    WARN,
    discord_ts,
    format_duration,
    module_color,
    parse_duration,
    utcnow,
)
from markets_bot.db.models import ModAction, Warning
from markets_bot.db.serialize import to_wire
from markets_bot.services.moderation import chain_ban, compromised, invite_revocation
from markets_bot.services.moderation.state import PendingBan, pending_bans, remember_ban
from markets_bot.services.moderation.warnings import (
    canonical_id,
    row_timestamp,
    select_recent,
    unique_warnings,
)

log = logging.getLogger(__name__)

MAX_TIMEOUT = 28 * 86400
BAN_DELETE_SECONDS = 7 * 86400
TWO_WEEKS = timedelta(days=14)
_SIMPLE_TIME_RE = re.compile(r"^(\d+)\s*(m|h|d)$", re.IGNORECASE)

ELEVATED = {
    "expulsar": "kick_members",
    "banear": "ban_members",
    "ban-temporal": "ban_members",
    "desbanear": "ban_members",
    "bloquear": "manage_channels",
    "desbloquear": "manage_channels",
}
ACTION_EMOJI = {"warn": "⚠️", "mute": "🔇", "tempmute": "🔇", "kick": "👢", "ban": "🔨", "tempban": "🔨",
                "unmute": "🔊", "unban": "✅"}
ACTION_NAME = {"warn": "ADVERTENCIA", "mute": "SILENCIO", "tempmute": "SILENCIO TEMPORAL", "kick": "EXPULSIÓN",
               "ban": "BAN", "tempban": "BAN TEMPORAL", "unmute": "DESILENCIADO", "unban": "DESBAN"}


def parse_simple_time(text: str) -> timedelta | None:
    """``30m`` / ``2h`` / ``7d`` (used by /purgar and /hackeado)."""
    match = _SIMPLE_TIME_RE.match(text.strip())
    if not match or int(match.group(1)) <= 0:
        return None
    amount, unit = int(match.group(1)), match.group(2).lower()
    return timedelta(minutes=amount) if unit == "m" else timedelta(hours=amount) if unit == "h" else timedelta(days=amount)


async def respond(interaction: discord.Interaction, content: str | None = None, *, ephemeral: bool = False,
                  **kwargs: Any) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=ephemeral, **kwargs)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral, **kwargs)


async def dm(user: discord.User | discord.Member, embed: discord.Embed) -> None:
    try:
        await user.send(embed=embed)
    except discord.HTTPException:
        pass  # DMs closed


def _source(row: dict[str, Any], guild_id: int) -> str:
    if row.get("guildId") == str(guild_id):
        return "local"
    return row.get("syncedFromGuildName") or row.get("syncedFromBot") or "otro servidor"


def _bot_can_manage(guild: discord.Guild, member: discord.Member) -> bool:
    return member.id != guild.owner_id and member.top_role < guild.me.top_role


class Moderation(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        bot.router.prefix("button", chain_ban.CONFIRM_PREFIX, lambda i: chain_ban.handle_button(bot, i))
        bot.router.prefix("button", chain_ban.CANCEL_PREFIX, lambda i: chain_ban.handle_button(bot, i))
        bot.router.prefix("button", invite_revocation.CONFIRM_PREFIX, lambda i: invite_revocation.handle_button(bot, i))
        bot.router.prefix("button", invite_revocation.CANCEL_PREFIX, lambda i: invite_revocation.handle_button(bot, i))
        bot.router.prefix("button", compromised.RELEASE_PREFIX, lambda i: compromised.handle_release(bot, i))

    async def cog_load(self) -> None:
        self.expire_temp_actions.start()

    async def cog_unload(self) -> None:
        self.expire_temp_actions.cancel()

    # ── Linked (peer) history ────────────────────────────────────────────

    async def linked_warnings(self, guild_id: int, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        async with self.bot.db.session() as session:
            local = (await session.execute(
                select(Warning).where(Warning.guild_id == str(guild_id), Warning.user_id == str(user_id))
                .order_by(Warning.created_at.desc()).limit(limit)
            )).scalars().all()
        rows = [to_wire(w) for w in local]
        for result in await self.bot.peers.broadcast(
            "moderation/warnings/query", {"userId": str(user_id), "limit": limit}, self.bot.peers.moderation_peers
        ):
            data = result.data if isinstance(result.data, dict) else {}
            rows.extend(r for r in data.get("rows", []) if isinstance(r, dict))
        return unique_warnings(rows)[:limit]

    async def linked_actions(self, guild_id: int, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
        async with self.bot.db.session() as session:
            local = (await session.execute(
                select(ModAction).where(ModAction.guild_id == str(guild_id), ModAction.user_id == str(user_id))
                .order_by(ModAction.created_at.desc()).limit(limit)
            )).scalars().all()
        rows = [to_wire(a) for a in local]
        for result in await self.bot.peers.broadcast(
            "moderation/actions/query", {"userId": str(user_id), "limit": limit}, self.bot.peers.moderation_peers
        ):
            data = result.data if isinstance(result.data, dict) else {}
            rows.extend(r for r in data.get("rows", []) if isinstance(r, dict))
        rows.sort(key=row_timestamp, reverse=True)
        return rows[:limit]

    @staticmethod
    def _peer_deleted(results: list[Any]) -> int:
        total = 0
        for result in results:
            count = result.data.get("deleted") if isinstance(result.data, dict) else None
            total += count if isinstance(count, int) else 0
        return total

    # ── /mod ─────────────────────────────────────────────────────────────

    mod = app_commands.Group(
        name="mod", description="Comandos de moderación", guild_only=True,
        default_permissions=discord.Permissions(moderate_members=True),
        extras={"module": "moderation", "cooldown": 3, "permissions": ["moderate_members"]},
    )

    async def _elevated(self, interaction: discord.Interaction, sub: str) -> bool:
        needed = ELEVATED.get(sub)
        if needed and not getattr(interaction.permissions, needed):
            await respond(interaction, "No tienes el permiso necesario para ejecutar esta acción de moderación.",
                          ephemeral=True)
            return False
        return True

    @mod.command(name="advertir", description="Advertir a un usuario")
    @app_commands.describe(usuario="Usuario a advertir", razon="Razón de la advertencia",
                           aislamiento="Tiempo de aislamiento opcional (ej. 30m, 2h, 3d; máximo 28d)")
    async def warn(self, interaction: discord.Interaction, usuario: discord.User, razon: str | None = None,
                   aislamiento: app_commands.Range[str, 1, 30] | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        reason = razon or "Sin razón proporcionada"
        isolation = parse_duration(aislamiento) if aislamiento else None
        if usuario.id == interaction.user.id:
            await respond(interaction, "No puedes advertirte a ti mismo.", ephemeral=True)
            return
        if aislamiento and not isolation:
            await respond(interaction, "Duración de aislamiento inválida. Usa formatos como `30m`, `2h`, `1d` o `1d12h`.",
                          ephemeral=True)
            return
        if isolation and isolation > MAX_TIMEOUT:
            await respond(interaction, "El aislamiento máximo permitido por Discord es de 28 días.", ephemeral=True)
            return
        await interaction.response.defer()
        if isolation:
            try:
                member = await guild.fetch_member(usuario.id)
            except discord.HTTPException:
                await respond(interaction, "No puedo aislarlo porque el usuario no está en este servidor.", ephemeral=True)
                return
            if not _bot_can_manage(guild, member):
                await respond(interaction, "No puedo aislar a este usuario por la jerarquía de roles.", ephemeral=True)
                return
            await member.timeout(timedelta(seconds=isolation), reason=f"Advertencia: {reason}")

        gid, uid, mid = str(guild.id), str(usuario.id), str(interaction.user.id)
        async with self.bot.db.session() as session:
            if isolation:
                # An older active record must not remove the replacement timeout early.
                await session.execute(update(ModAction).where(
                    ModAction.guild_id == gid, ModAction.user_id == uid, ModAction.action == "tempmute",
                    ModAction.active.is_(True)).values(active=False))
            warning = Warning(guild_id=gid, user_id=uid, moderator_id=mid, reason=reason)
            action = ModAction(guild_id=gid, user_id=uid, moderator_id=mid, action="warn", reason=reason)
            session.add_all([warning, action])
            if isolation:
                session.add(ModAction(guild_id=gid, user_id=uid, moderator_id=mid, action="tempmute",
                                      reason=f"Aislamiento por advertencia: {reason}", duration=isolation,
                                      expires_at=utcnow() + timedelta(seconds=isolation)))
            await session.flush()
            warning_payload = {
                "id": warning.id, "actionId": action.id, "userId": uid, "moderatorId": mid, "reason": reason,
                "createdAt": to_wire(warning)["createdAt"], "fromGuildId": gid, "fromGuildName": guild.name,
                "fromBot": self.bot.identity,
            }
        await self.bot.peers.broadcast("moderation/warnings", warning_payload, self.bot.peers.moderation_peers)
        total = len(await self.linked_warnings(guild.id, usuario.id, 200))

        embed = mod_embed("warn", guild, usuario, interaction.user.id, interaction.user.name, reason=reason,
                          duration=format_duration(isolation) if isolation else None,
                          extra=[("Advertencias totales", str(total), True)])
        await interaction.followup.send(embed=embed)
        notice = discord.Embed(color=WARN, title=f"Fuiste advertido en {guild.name}", timestamp=discord.utils.utcnow())
        notice.add_field(name="Razón", value=reason, inline=False)
        if isolation:
            notice.add_field(name="Aislamiento temporal", value=format_duration(isolation), inline=True)
        await dm(usuario, notice)
        config = await self.bot.configs.get(guild.id)
        await send_to(guild, config.warn_log_channel_id or config.mod_log_channel_id, embed=embed)

    @mod.command(name="advertencias", description="Ver advertencias de un usuario")
    @app_commands.describe(usuario="Usuario a consultar")
    async def warnings(self, interaction: discord.Interaction, usuario: discord.User) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        rows = await self.linked_warnings(interaction.guild_id, usuario.id, 10)
        if not rows:
            await respond(interaction, f"{usuario.name} no tiene advertencias.", ephemeral=True)
            return
        lines = [
            f"**{i}.** {w.get('reason')}\n   Por <@{w.get('moderatorId')}> — {_source(w, interaction.guild_id)} — "
            f"<t:{int(row_timestamp(w))}:R>"
            for i, w in enumerate(rows, 1)
        ]
        embed = discord.Embed(color=WARN, title=f"Advertencias de {usuario.name}", description="\n\n".join(lines)[:4096],
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"{len(rows)} advertencia(s) en total")
        await respond(interaction, embed=embed, ephemeral=True)

    @mod.command(name="limpiar-advertencias", description="Borrar todas las advertencias de un usuario")
    @app_commands.describe(usuario="Usuario a limpiar")
    async def clear_warnings(self, interaction: discord.Interaction, usuario: discord.User) -> None:
        if not interaction.permissions.administrator:
            await respond(interaction, "Solo los administradores pueden borrar advertencias.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        gid = str(interaction.guild_id)
        async with self.bot.db.session() as session:
            local = await session.execute(delete(Warning).where(Warning.guild_id == gid, Warning.user_id == str(usuario.id)))
        peers = await self.bot.peers.broadcast(
            "moderation/warnings/delete-user", {"userId": str(usuario.id), "fromGuildId": gid, "fromBot": self.bot.identity},
            self.bot.peers.moderation_peers)
        total = local.rowcount + self._peer_deleted(peers)
        await respond(interaction, f"Se borraron **{total}** advertencia(s) de {usuario.name} entre los servidores "
                                   "conectados.", ephemeral=True)

    @mod.command(name="quitar-advertencias", description="Quitar una cantidad de las advertencias más recientes")
    @app_commands.describe(usuario="Usuario al que se le quitarán", cantidad="Número de advertencias que deseas quitar",
                           razon="Motivo opcional del ajuste")
    async def remove_warnings(self, interaction: discord.Interaction, usuario: discord.User,
                              cantidad: app_commands.Range[int, 1, 100],
                              razon: app_commands.Range[str, 1, 300] | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        if not interaction.permissions.administrator:
            await respond(interaction, "Solo los administradores pueden quitar advertencias.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        reason = (razon or "").strip() or "Ajuste manual de advertencias"
        selected = select_recent(await self.linked_warnings(guild.id, usuario.id, 200), cantidad)
        if not selected:
            await respond(interaction, f"{usuario.name} no tiene advertencias para quitar.", ephemeral=True)
            return
        ids = [canonical_id(w) for w in selected]
        gid, uid = str(guild.id), str(usuario.id)
        async with self.bot.db.session() as session:
            local = await session.execute(delete(Warning).where(
                Warning.guild_id == gid, Warning.user_id == uid,
                or_(Warning.id.in_(ids), Warning.source_warning_id.in_(ids))))
        peers = await self.bot.peers.broadcast(
            "moderation/warnings/delete-many",
            {"userId": uid, "warningIds": ids, "fromGuildId": gid, "fromBot": self.bot.identity},
            self.bot.peers.moderation_peers)
        remaining = len(await self.linked_warnings(guild.id, usuario.id, 200))
        async with self.bot.db.session() as session:
            session.add(ModAction(guild_id=gid, user_id=uid, moderator_id=str(interaction.user.id),
                                  action="warnings_removed",
                                  reason=f"{reason} · {len(selected)} advertencia(s) retirada(s)"))
        embed = discord.Embed(color=module_color("moderation"), title="Advertencias ajustadas",
                              description=f"Se quitaron **{len(selected)}** advertencia(s) reciente(s) de {usuario.mention}.",
                              timestamp=discord.utils.utcnow())
        embed.add_field(name="Advertencias restantes", value=str(remaining), inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Razón", value=reason, inline=False)
        embed.set_footer(text=f"Registros eliminados: {local.rowcount + self._peer_deleted(peers)}")
        await respond(interaction, embed=embed, ephemeral=True)
        await send_mod_log(self.bot, guild, embed)

    @mod.command(name="silenciar", description="Silenciar a un usuario (timeout)")
    @app_commands.describe(usuario="Usuario a silenciar", duracion="Duración (ej. 1h, 30m, 1d)", razon="Razón")
    async def mute(self, interaction: discord.Interaction, usuario: discord.Member, duracion: str,
                   razon: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        reason = razon or "Sin razón proporcionada"
        seconds = parse_duration(duracion)
        if not seconds:
            await respond(interaction, "Duración inválida. Usa formatos como `1h`, `30m`, `1d`.", ephemeral=True)
            return
        if seconds > MAX_TIMEOUT:
            await respond(interaction, "La duración máxima del silencio es de 28 días.", ephemeral=True)
            return
        if not _bot_can_manage(guild, usuario):
            await respond(interaction, "No puedo silenciar a este usuario (jerarquía de roles).", ephemeral=True)
            return
        await usuario.timeout(timedelta(seconds=seconds), reason=reason)
        async with self.bot.db.session() as session:
            session.add(ModAction(guild_id=str(guild.id), user_id=str(usuario.id), moderator_id=str(interaction.user.id),
                                  action="tempmute", reason=reason, duration=seconds,
                                  expires_at=utcnow() + timedelta(seconds=seconds)))
        embed = mod_embed("mute", guild, usuario, interaction.user.id, interaction.user.name, reason=reason,
                          duration=format_duration(seconds))
        await respond(interaction, embed=embed)
        await send_mod_log(self.bot, guild, embed)

    @mod.command(name="desilenciar", description="Quitar silencio a un usuario")
    @app_commands.describe(usuario="Usuario a desilenciar")
    async def unmute(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        guild = interaction.guild
        assert guild is not None
        await usuario.timeout(None, reason=f"Desilenciado por {interaction.user.name}")
        config = await self.bot.configs.get(guild.id)
        if config.mute_role_id and usuario.get_role(int(config.mute_role_id)):
            with contextlib.suppress(discord.HTTPException):
                await usuario.remove_roles(discord.Object(int(config.mute_role_id)))
        async with self.bot.db.session() as session:
            await session.execute(update(ModAction).where(
                ModAction.guild_id == str(guild.id), ModAction.user_id == str(usuario.id),
                ModAction.action.in_(("tempmute", "mute")), ModAction.active.is_(True)).values(active=False))
        await respond(interaction, f"{usuario.mention} ha sido desilenciado.")

    @mod.command(name="expulsar", description="Expulsar a un usuario del servidor")
    @app_commands.describe(usuario="Usuario a expulsar", razon="Razón")
    async def kick(self, interaction: discord.Interaction, usuario: discord.Member, razon: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        if not await self._elevated(interaction, "expulsar"):
            return
        reason = razon or "Sin razón proporcionada"
        if not _bot_can_manage(guild, usuario):
            await respond(interaction, "No puedo expulsar a este usuario (jerarquía de roles).", ephemeral=True)
            return
        notice = discord.Embed(color=ERROR, title=f"Fuiste expulsado de {guild.name}", timestamp=discord.utils.utcnow())
        notice.add_field(name="Razón", value=reason)
        await dm(usuario, notice)
        await usuario.kick(reason=reason)
        async with self.bot.db.session() as session:
            session.add(ModAction(guild_id=str(guild.id), user_id=str(usuario.id),
                                  moderator_id=str(interaction.user.id), action="kick", reason=reason))
        embed = mod_embed("kick", guild, usuario, interaction.user.id, interaction.user.name, reason=reason)
        await respond(interaction, embed=embed)
        await send_mod_log(self.bot, guild, embed)

    async def _ban(self, interaction: discord.Interaction, user: discord.User, reason: str, *,
                   audit_reason: str | None = None, delete_seconds: int = BAN_DELETE_SECONDS,
                   action: str = "ban", duration: int | None = None) -> bool:
        guild = interaction.guild
        assert guild is not None
        member = guild.get_member(user.id)
        if member is not None and not _bot_can_manage(guild, member):
            await respond(interaction, "No puedo banear a este usuario (jerarquía de roles).", ephemeral=True)
            return False
        remember_ban(user.id, PendingBan(str(guild.id), str(interaction.user.id), reason, True))
        await guild.ban(user, reason=audit_reason or reason, delete_message_seconds=delete_seconds)
        async with self.bot.db.session() as session:
            session.add(ModAction(
                guild_id=str(guild.id), user_id=str(user.id), moderator_id=str(interaction.user.id), action=action,
                reason=reason, duration=duration,
                expires_at=utcnow() + timedelta(seconds=duration) if duration else None,
            ))
        return True

    @mod.command(name="banear", description="Banear a un usuario")
    @app_commands.describe(usuario="Usuario a banear", razon="Razón", dias="Días de mensajes a eliminar (0-7)",
                           canal="Canal donde publicar el cartel de ban (por defecto: canal de bans)",
                           cadena="Banear todo el árbol de invitaciones relacionado (staff excluido)",
                           niveles="Limitar la distancia en invitaciones (1-10); si se omite, todo el árbol")
    async def ban_sub(self, interaction: discord.Interaction, usuario: discord.User, razon: str | None = None,
                      dias: app_commands.Range[int, 0, 7] = 7, canal: discord.TextChannel | None = None,
                      cadena: bool = False, niveles: app_commands.Range[int, 1, 10] | None = None) -> None:
        if not await self._elevated(interaction, "banear"):
            return
        reason = razon or "Sin razón proporcionada"
        if cadena:
            await interaction.response.defer(ephemeral=True)
            await chain_ban.prepare(self.bot, interaction, usuario, reason, dias, niveles)
            return
        guild = interaction.guild
        assert guild is not None
        notice = discord.Embed(color=ERROR, title=f"Fuiste baneado de {guild.name}", timestamp=discord.utils.utcnow())
        notice.add_field(name="Razón", value=reason)
        await dm(usuario, notice)
        if not await self._ban(interaction, usuario, reason, delete_seconds=dias * 86400):
            return
        embed = mod_embed("ban", guild, usuario, interaction.user.id, interaction.user.name, reason=reason)
        await respond(interaction, embed=embed)
        if canal is not None:
            with contextlib.suppress(discord.HTTPException):
                await canal.send(embed=embed)

    @mod.command(name="ban-temporal", description="Banear temporalmente a un usuario")
    @app_commands.describe(usuario="Usuario a banear temporalmente", duracion="Duración (ej. 1d, 1w)", razon="Razón")
    async def tempban(self, interaction: discord.Interaction, usuario: discord.User, duracion: str,
                      razon: str | None = None) -> None:
        if not await self._elevated(interaction, "ban-temporal"):
            return
        guild = interaction.guild
        assert guild is not None
        reason = razon or "Sin razón proporcionada"
        seconds = parse_duration(duracion)
        if not seconds:
            await respond(interaction, "Duración inválida.", ephemeral=True)
            return
        if not await self._ban(interaction, usuario, reason, audit_reason=f"Ban temporal: {reason}",
                               action="tempban", duration=seconds):
            return
        embed = mod_embed("ban", guild, usuario, interaction.user.id, interaction.user.name, reason=reason,
                          duration=format_duration(seconds))
        await respond(interaction, embed=embed)

    @mod.command(name="desbanear", description="Desbanear a un usuario")
    @app_commands.describe(userid="ID del usuario a desbanear")
    async def unban(self, interaction: discord.Interaction, userid: str) -> None:
        if not await self._elevated(interaction, "desbanear"):
            return
        guild = interaction.guild
        assert guild is not None
        try:
            entry = await guild.fetch_ban(discord.Object(int(userid)))
            await guild.unban(entry.user, reason=f"Desbaneado por {interaction.user.name}")
        except (ValueError, discord.HTTPException):
            await respond(interaction, "No se pudo desbanear a ese usuario. Verifica que el ID sea correcto.",
                          ephemeral=True)
            return
        async with self.bot.db.session() as session:
            await session.execute(update(ModAction).where(
                ModAction.guild_id == str(guild.id), ModAction.user_id == userid,
                ModAction.action.in_(("ban", "tempban")), ModAction.active.is_(True)).values(active=False))
        embed = mod_embed("unban", guild, entry.user, interaction.user.id, interaction.user.name)
        await respond(interaction, embed=embed)

    @mod.command(name="bloquear", description="Bloquear un canal (impedir envío de mensajes)")
    @app_commands.describe(canal="Canal a bloquear", razon="Razón")
    async def lock(self, interaction: discord.Interaction, canal: discord.TextChannel | None = None,
                   razon: str | None = None) -> None:
        if not await self._elevated(interaction, "bloquear"):
            return
        channel = canal or interaction.channel
        if not isinstance(channel, discord.TextChannel) or interaction.guild is None:
            await respond(interaction, "Canal de texto inválido.", ephemeral=True)
            return
        reason = razon or "Canal bloqueado por un moderador"
        await channel.set_permissions(interaction.guild.default_role, send_messages=False)
        await channel.send(embed=discord.Embed(color=ERROR, title="🔒 Canal Bloqueado",
                                               description=f"Este canal ha sido bloqueado.\n**Razón:** {reason}",
                                               timestamp=discord.utils.utcnow()))
        await respond(interaction, f"{channel.mention} ha sido bloqueado.", ephemeral=True)

    @mod.command(name="desbloquear", description="Desbloquear un canal")
    @app_commands.describe(canal="Canal a desbloquear")
    async def unlock(self, interaction: discord.Interaction, canal: discord.TextChannel | None = None) -> None:
        if not await self._elevated(interaction, "desbloquear"):
            return
        channel = canal or interaction.channel
        if not isinstance(channel, discord.TextChannel) or interaction.guild is None:
            await respond(interaction, "Canal de texto inválido.", ephemeral=True)
            return
        await channel.set_permissions(interaction.guild.default_role, send_messages=None)
        await channel.send(embed=discord.Embed(color=OK, title="🔓 Canal Desbloqueado",
                                               description="Este canal ha sido desbloqueado.",
                                               timestamp=discord.utils.utcnow()))
        await respond(interaction, f"{channel.mention} ha sido desbloqueado.", ephemeral=True)

    @mod.command(name="historial", description="Ver historial de moderación de un usuario")
    @app_commands.describe(usuario="Usuario a consultar")
    async def history(self, interaction: discord.Interaction, usuario: discord.User) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        actions = await self.linked_actions(interaction.guild_id, usuario.id, 15)
        if not actions:
            await respond(interaction, f"No hay historial de moderación para {usuario.name}.", ephemeral=True)
            return
        lines = [
            f"{ACTION_EMOJI.get(a.get('action', ''), '📋')} **{ACTION_NAME.get(a.get('action', ''), str(a.get('action', '')).upper())}**"
            f" — {a.get('reason')}\nPor <@{a.get('moderatorId')}> — {_source(a, interaction.guild_id)} — "
            f"<t:{int(row_timestamp(a))}:R>{' (activo)' if a.get('active') else ''}"
            for a in actions
        ]
        embed = discord.Embed(color=module_color("moderation"), title=f"Historial de Moderación: {usuario.name}",
                              description="\n\n".join(lines)[:4096], timestamp=discord.utils.utcnow())
        await respond(interaction, embed=embed, ephemeral=True)

    # ── /ban (quick) ─────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Banear a un usuario del servidor",
                          extras={"module": "moderation", "cooldown": 3, "permissions": ["ban_members"]})
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    @app_commands.describe(usuario="Usuario a banear", razon="Razón del ban")
    async def quick_ban(self, interaction: discord.Interaction, usuario: discord.User, razon: str) -> None:
        guild = interaction.guild
        assert guild is not None
        notice = discord.Embed(color=ERROR, title=f"Has sido baneado de {guild.name}", timestamp=discord.utils.utcnow())
        notice.add_field(name="Razón", value=razon)
        member = guild.get_member(usuario.id)
        if member is not None and not _bot_can_manage(guild, member):
            await respond(interaction, "No puedo banear a este usuario (jerarquía de roles).", ephemeral=True)
            return
        await dm(usuario, notice)
        if await self._ban(interaction, usuario, razon):
            # The full log embed is posted by the ban event.
            await respond(interaction, f"✅ **{usuario.name}** ha sido baneado y se eliminaron sus mensajes recientes. "
                                       f"Razón: `{razon}`", ephemeral=True)

    # ── Message cleanup ──────────────────────────────────────────────────

    @app_commands.command(name="limpiar", description="Eliminar mensajes de un canal",
                          extras={"module": "moderation", "cooldown": 3, "permissions": ["manage_messages"]})
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.describe(cantidad="Número de mensajes a eliminar (1–100)",
                           usuario="Eliminar solo los mensajes de este usuario")
    async def clean(self, interaction: discord.Interaction, cantidad: app_commands.Range[int, 1, 100],
                    usuario: discord.User | None = None) -> None:
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            await respond(interaction, "Canal inválido.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        fetch_limit = min(cantidad * 5, 100) if usuario else cantidad
        cutoff = discord.utils.utcnow() - TWO_WEEKS
        messages = [
            m async for m in channel.history(limit=fetch_limit)
            if (usuario is None or m.author.id == usuario.id) and m.created_at > cutoff
        ][:cantidad]
        if not messages:
            await respond(interaction, "No hay mensajes eliminables en este canal.", ephemeral=True)
            return
        await channel.delete_messages(messages)
        await respond(interaction, f"✅ Se eliminaron **{len(messages)}** mensaje(s)"
                                   f"{f' de **{usuario.name}**' if usuario else ''}.", ephemeral=True)

    async def _purge_channel(self, channel: discord.TextChannel, limit: int, user_id: int | None,
                             since: Any) -> int:
        perms = channel.permissions_for(channel.guild.me)
        if not (perms.manage_messages and perms.read_message_history):
            return 0
        cutoff = discord.utils.utcnow() - TWO_WEEKS
        try:
            batch = [m async for m in channel.history(limit=100)]
        except discord.HTTPException:
            return 0
        targets = [
            m for m in batch
            if (since is None or m.created_at > since) and m.created_at > cutoff and not m.pinned
            and (user_id is None or m.author.id == user_id)
        ][:limit]
        if not targets:
            return 0
        if len(targets) == 1:
            try:
                await targets[0].delete()
                return 1
            except discord.HTTPException:
                return 0
        try:
            await channel.delete_messages(targets)
            return len(targets)
        except discord.HTTPException:
            count = 0
            for message in targets:
                try:
                    await message.delete()
                    count += 1
                except discord.HTTPException:
                    pass
                await asyncio.sleep(0.1)
            return count

    @app_commands.command(name="purgar",
                          description="Eliminar mensajes de un usuario en todos los canales o en uno específico",
                          extras={"module": "moderation", "cooldown": 5, "permissions": ["manage_messages"]})
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.describe(usuario="Usuario cuyos mensajes eliminar",
                           usuario_id="ID del usuario (si ya no está en el servidor)",
                           tiempo="Rango de tiempo: 30m · 2h · 6h · 1d · 7d · 14d",
                           cantidad="Máximo de mensajes por canal (1-100, por defecto 100)",
                           canal="Canal específico (por defecto: todos los canales)")
    async def purge(self, interaction: discord.Interaction, usuario: discord.User | None = None,
                    usuario_id: str | None = None, tiempo: str | None = None,
                    cantidad: app_commands.Range[int, 1, 100] = 100, canal: discord.TextChannel | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        raw_id = (usuario_id or "").strip()
        if raw_id and not re.fullmatch(r"\d{17,20}", raw_id):
            await respond(interaction, "❌ `usuario_id` inválido. Debe ser un número de 17-20 dígitos.", ephemeral=True)
            return
        user_id = usuario.id if usuario else int(raw_id) if raw_id else None
        since = None
        if tiempo:
            span = parse_simple_time(tiempo)
            if span is None:
                await respond(interaction, "❌ Formato de tiempo inválido. Usa: `30m`, `2h`, `1d`, `7d`, etc.",
                              ephemeral=True)
                return
            if span > TWO_WEEKS:
                await respond(interaction, "❌ El rango máximo es 14 días (límite de Discord).", ephemeral=True)
                return
            since = discord.utils.utcnow() - span
        await interaction.response.defer(ephemeral=True)

        def extra_fields(embed: discord.Embed) -> None:
            if user_id:
                embed.add_field(name="👤 Usuario", value=f"<@{user_id}>", inline=True)
            if tiempo:
                embed.add_field(name="⏱️ Rango", value=f"Últimos **{tiempo}**", inline=True)
            embed.set_footer(text=f"Ejecutado por {interaction.user.name}")

        if canal is not None:
            deleted = await self._purge_channel(canal, cantidad, user_id, since)
            embed = discord.Embed(color=module_color("moderation"), title="🗑️ Purga completada",
                                  timestamp=discord.utils.utcnow())
            embed.add_field(name="📊 Eliminados", value=f"**{deleted}**", inline=True)
            embed.add_field(name="📁 Canal", value=canal.mention, inline=True)
            extra_fields(embed)
            await respond(interaction, embed=embed, ephemeral=True)
            return

        channels = [c for c in guild.text_channels if c.permissions_for(guild.me).view_channel]
        total, results = 0, []
        for channel in channels:
            deleted = await self._purge_channel(channel, cantidad, user_id, since)
            if deleted:
                total += deleted
                results.append(f"{channel.mention}: **{deleted}**")
            await asyncio.sleep(0.35)
        embed = discord.Embed(color=module_color("moderation") if total else WARN,
                              title="🗑️ Purga completada — todos los canales", timestamp=discord.utils.utcnow())
        embed.add_field(name="📊 Total eliminados", value=f"**{total}**", inline=True)
        embed.add_field(name="📁 Canales revisados", value=f"**{len(channels)}**", inline=True)
        extra_fields(embed)
        if results:
            embed.add_field(name="📋 Detalle", value="\n".join(results)[:1024], inline=False)
        else:
            embed.description = "No se encontraron mensajes eliminables."
        await respond(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="modolento", description="Establecer o quitar el modo lento de un canal",
                          extras={"module": "moderation", "cooldown": 5, "permissions": ["manage_channels"]})
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.describe(duracion='Duración del modo lento (ej. 5s, 1m, 1h) o "off" para desactivar',
                           canal="Canal (por defecto el actual)")
    async def slowmode(self, interaction: discord.Interaction, duracion: str,
                       canal: discord.TextChannel | None = None) -> None:
        channel = canal or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await respond(interaction, "Canal de texto inválido.", ephemeral=True)
            return
        if duracion.lower() in ("off", "0"):
            seconds = 0
        else:
            parsed = parse_duration(duracion)
            if not parsed:
                await respond(interaction, "Duración inválida. Usa formatos como `5s`, `1m`, `1h`, o `off`.",
                              ephemeral=True)
                return
            seconds = parsed
        if seconds > 21600:
            await respond(interaction, "El modo lento máximo es de 6 horas (21600 segundos).", ephemeral=True)
            return
        await channel.edit(slowmode_delay=seconds, reason=f"Establecido por {interaction.user.name}")
        text = (f"Modo lento desactivado en {channel.mention}." if seconds == 0
                else f"Modo lento establecido a **{seconds}s** en {channel.mention}.")
        await respond(interaction, embed=discord.Embed(color=module_color("moderation"), description=text,
                                                       timestamp=discord.utils.utcnow()))

    # ── /rol ─────────────────────────────────────────────────────────────

    rol = app_commands.Group(name="rol", description="Gestionar roles de los miembros", guild_only=True,
                             default_permissions=discord.Permissions(manage_roles=True),
                             extras={"module": "moderation", "cooldown": 5, "permissions": ["manage_roles"]})

    @staticmethod
    def _can_manage_role(interaction: discord.Interaction, role: discord.Role) -> bool:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return False
        return role < guild.me.top_role and (role < member.top_role or member.id == guild.owner_id)

    @rol.command(name="dar", description="Dar un rol a un miembro")
    @app_commands.describe(usuario="Usuario objetivo", rol="Rol a dar")
    async def role_add(self, interaction: discord.Interaction, usuario: discord.Member, rol: discord.Role) -> None:
        if not self._can_manage_role(interaction, rol):
            await respond(interaction, "No puedes gestionar este rol (puede ser superior al tuyo).", ephemeral=True)
            return
        await usuario.add_roles(rol)
        await respond(interaction, embed=discord.Embed(color=module_color("moderation"),
                                                       description=f"Se dio {rol.mention} a {usuario.mention}.",
                                                       timestamp=discord.utils.utcnow()))

    @rol.command(name="quitar", description="Quitar un rol a un miembro")
    @app_commands.describe(usuario="Usuario objetivo", rol="Rol a quitar")
    async def role_remove(self, interaction: discord.Interaction, usuario: discord.Member, rol: discord.Role) -> None:
        if not self._can_manage_role(interaction, rol):
            await respond(interaction, "No puedes gestionar este rol.", ephemeral=True)
            return
        await usuario.remove_roles(rol)
        await respond(interaction, embed=discord.Embed(color=module_color("moderation"),
                                                       description=f"Se quitó {rol.mention} de {usuario.mention}.",
                                                       timestamp=discord.utils.utcnow()))

    @rol.command(name="todos", description="Dar o quitar un rol a todos los miembros")
    @app_commands.describe(rol="Rol a dar/quitar", accion="Dar o quitar")
    @app_commands.choices(accion=[app_commands.Choice(name="Dar a todos", value="add"),
                                  app_commands.Choice(name="Quitar a todos", value="remove")])
    async def role_all(self, interaction: discord.Interaction, rol: discord.Role, accion: str) -> None:
        guild = interaction.guild
        assert guild is not None
        if not self._can_manage_role(interaction, rol):
            await respond(interaction, "No puedes gestionar este rol.", ephemeral=True)
            return
        await interaction.response.defer()
        count = 0
        async for member in guild.fetch_members(limit=None):
            has = member.get_role(rol.id) is not None
            try:
                if accion == "add" and not has:
                    await member.add_roles(rol)
                    count += 1
                elif accion == "remove" and has:
                    await member.remove_roles(rol)
                    count += 1
            except discord.HTTPException:
                continue
        text = (f"Se dio {rol.mention} a **{count}** miembro(s)." if accion == "add"
                else f"Se quitó {rol.mention} de **{count}** miembro(s).")
        await respond(interaction, embed=discord.Embed(color=module_color("moderation"), description=text,
                                                       timestamp=discord.utils.utcnow()))

    @rol.command(name="info", description="Ver información de un rol")
    @app_commands.describe(rol="Rol a inspeccionar")
    async def role_info(self, interaction: discord.Interaction, rol: discord.Role) -> None:
        embed = discord.Embed(color=rol.color.value or 0x99AAB5, title=f"Rol: {rol.name}", timestamp=discord.utils.utcnow())
        for name, value in (
            ("ID", str(rol.id)), ("Color", str(rol.color)), ("Posición", str(rol.position)),
            ("Miembros", str(len(rol.members))), ("Mencionable", "Sí" if rol.mentionable else "No"),
            ("Separado", "Sí" if rol.hoist else "No"), ("Creado", discord_ts(rol.created_at)),
            ("Gestionado", "Sí (bot/integración)" if rol.managed else "No"),
        ):
            embed.add_field(name=name, value=value, inline=True)
        await respond(interaction, embed=embed)

    # ── /hackeado & /revocar-invitaciones ────────────────────────────────

    @app_commands.command(name="hackeado",
                          description="Contiene una cuenta hackeada: aislamiento, borra sus mensajes e invitaciones y le avisa",
                          extras={"module": "moderation", "cooldown": 5, "permissions": ["moderate_members"]})
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.describe(
        usuario="Usuario que fue hackeado",
        mensajes="Borrar mensajes de este periodo: 30m, 2h, 1d… (por defecto: 2h, máx. 14d)",
        aislamiento="Duración del aislamiento: 1h, 24h, 7d… (por defecto: 24h, máx. 28d)",
        razon="Razón adicional (por defecto: cuenta comprometida/hackeada)",
        revocar_invitaciones="Revocar las invitaciones que creó esta cuenta (por defecto: sí)",
        avisar_usuario="Enviarle por MD cómo recuperar su cuenta (por defecto: sí)",
    )
    async def hacked(self, interaction: discord.Interaction, usuario: discord.User, mensajes: str = "2h",
                     aislamiento: str = "24h", razon: str = "cuenta comprometida/hackeada",
                     revocar_invitaciones: bool = True, avisar_usuario: bool = True) -> None:
        guild = interaction.guild
        assert guild is not None
        if usuario.id == interaction.user.id:
            await respond(interaction, "❌ No puedes usar este comando contigo mismo.", ephemeral=True)
            return
        if usuario.bot:
            await respond(interaction, "❌ Este comando es para cuentas de usuarios, no para bots.", ephemeral=True)
            return
        messages_span = parse_simple_time(mensajes)
        if messages_span is None or messages_span > TWO_WEEKS:
            await respond(interaction, "❌ Rango de mensajes inválido. Usa `30m`, `2h`, `1d`… (máximo 14 días).",
                          ephemeral=True)
            return
        timeout_span = parse_simple_time(aislamiento)
        if timeout_span is None or timeout_span > timedelta(days=28):
            await respond(interaction, "❌ Duración de aislamiento inválida. Usa `1h`, `24h`, `7d`… (máximo 28 días).",
                          ephemeral=True)
            return
        await interaction.response.send_message(
            f"⏳ Aislando a {usuario.mention} y buscando sus mensajes de las últimas **{mensajes}** en todos los canales…",
            ephemeral=True)
        result = await compromised.cleanup(
            guild, usuario, messages_since=messages_span, timeout=timeout_span,
            reason=f"[HACKEADO] {razon} · por {interaction.user.name}",
            revoke_invites=revocar_invitaciones, notify_user=avisar_usuario)
        embed = compromised.cleanup_embed(usuario, interaction.user.id, result, messages=mensajes,
                                          timeout=aislamiento, reason=razon)
        await compromised.log_cleanup(self.bot, guild, embed)
        await interaction.edit_original_response(
            content="Listo. Cuando el dueño recupere la cuenta, usa el botón para quitar el aislamiento."
            if result.timeout_ok else "Mensajes procesados, pero el aislamiento no se pudo aplicar.",
            embed=embed, view=compromised.release_view(usuario.id) if result.timeout_ok else None)

    @app_commands.command(name="revocar-invitaciones",
                          description="Revocar invitaciones activas de un usuario o de todo el servidor",
                          extras={"module": "moderation", "cooldown": 5, "permissions": ["administrator"]})
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(alcance="Selecciona qué invitaciones deseas revocar",
                           usuario="Usuario creador de las invitaciones (solo para alcance por usuario)")
    @app_commands.choices(alcance=[app_commands.Choice(name="Invitaciones de un usuario", value="user"),
                                   app_commands.Choice(name="Todas las invitaciones del servidor", value="server")])
    async def revoke_invites(self, interaction: discord.Interaction, alcance: str,
                             usuario: discord.User | None = None) -> None:
        log.info("[InviteRevocation] preview guild=%s moderator=%s scope=%s target=%s",
                 interaction.guild_id, interaction.user.id, alcance, usuario.id if usuario else None)
        await invite_revocation.prepare(self.bot, interaction, alcance, usuario)

    # ── Temp action expiry ───────────────────────────────────────────────

    @tasks.loop(seconds=30)
    @resilient
    async def expire_temp_actions(self) -> None:
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        async with self.bot.db.session() as session:
            expired = (await session.execute(select(ModAction).where(
                ModAction.guild_id.in_(guild_ids), ModAction.active.is_(True),
                ModAction.expires_at.is_not(None), ModAction.expires_at <= utcnow(),
                ModAction.action.in_(("tempmute", "tempban")),
            ))).scalars().all()
        for action in expired:
            guild = self.bot.get_guild(int(action.guild_id))
            if guild is None:
                continue
            config = await self.bot.configs.get(guild.id)
            try:
                if action.action == "tempmute":
                    member = guild.get_member(int(action.user_id))
                    if member is not None:
                        await member.timeout(None, reason="Temp mute expired")
                        if config.mute_role_id:
                            with contextlib.suppress(discord.HTTPException):
                                await member.remove_roles(discord.Object(int(config.mute_role_id)))
                else:
                    with contextlib.suppress(discord.HTTPException):
                        await guild.unban(discord.Object(int(action.user_id)), reason="Temp ban expired")
                async with self.bot.db.session() as session:
                    await session.execute(update(ModAction).where(ModAction.id == action.id).values(active=False))
                embed = discord.Embed(color=OK, title="Mute expirado" if action.action == "tempmute" else "Ban expirado",
                                      timestamp=discord.utils.utcnow())
                embed.add_field(name="Usuario", value=f"<@{action.user_id}>", inline=True)
                embed.add_field(name="Motivo original", value=action.reason, inline=True)
                await send_to(guild, config.mod_log_channel_id, embed=embed)
            except discord.HTTPException:
                log.exception("Error processing expired action %s", action.id)

    @expire_temp_actions.before_loop
    async def _before_expiry(self) -> None:
        await self.bot.wait_until_ready()


__all__ = ["Moderation", "pending_bans"]


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Moderation(bot))
