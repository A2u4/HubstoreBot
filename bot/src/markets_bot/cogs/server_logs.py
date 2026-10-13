"""Server activity logging: messages, channels, roles, members and voice.

Also keeps the in-memory cache behind ``/snipe`` (last 10 deleted messages per
channel, 5 minutes).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from markets_bot.bot import MarketsBot
from markets_bot.core.audit import audit_executor, send_audit, send_to, text_channel, truncate_audit_value
from markets_bot.core.dedupe import claim_side_effect
from markets_bot.core.utils import ERROR, OK, PINK, WARN, discord_ts, module_color, truncate

log = logging.getLogger(__name__)

CHANNEL_TYPE_NAMES = {
    discord.ChannelType.text: "Texto",
    discord.ChannelType.voice: "Voz",
    discord.ChannelType.category: "Categoria",
    discord.ChannelType.news: "Anuncios",
    discord.ChannelType.forum: "Foro",
    discord.ChannelType.stage_voice: "Escenario",
}

SNIPE_LIMIT = 10
SNIPE_TTL_SECONDS = 300


@dataclass(slots=True)
class DeletedMessage:
    author_name: str
    author_avatar: str | None
    content: str
    attachment_url: str | None
    deleted_at: datetime
    stored_at: float


class SnipeCache:
    def __init__(self) -> None:
        self._channels: dict[int, deque[DeletedMessage]] = {}

    def add(self, channel_id: int, item: DeletedMessage) -> None:
        stack = self._channels.setdefault(channel_id, deque(maxlen=SNIPE_LIMIT))
        stack.appendleft(item)

    def items(self, channel_id: int) -> list[DeletedMessage]:
        stack = self._channels.get(channel_id)
        if not stack:
            return []
        cutoff = time.monotonic() - SNIPE_TTL_SECONDS
        while stack and stack[-1].stored_at < cutoff:
            stack.pop()
        if not stack:
            self._channels.pop(channel_id, None)
        return list(stack)


def _member_embed(member: discord.Member, color: int, title: str) -> discord.Embed:
    embed = discord.Embed(color=color, title=title, timestamp=discord.utils.utcnow())
    embed.set_author(name=member.name, icon_url=member.display_avatar.url)
    embed.set_footer(text=f"ID de usuario: {member.id}")
    return embed


class ServerLogs(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self.snipes = SnipeCache()

    async def _audit_channel_id(self, guild: discord.Guild, *, voice: bool = False) -> str | None:
        """Logging target when the logging module is on (voice log falls back to audit, then mod log)."""
        config = await self.bot.configs.get(guild.id)
        if not config.logging_enabled:
            return None
        if voice:
            return config.voice_log_channel_id or config.audit_log_channel_id or config.mod_log_channel_id
        return config.audit_log_channel_id or config.mod_log_channel_id

    async def _audit(self, guild: discord.Guild, embed: discord.Embed, channel_id: str) -> None:
        if text_channel(guild, channel_id) is not None:
            await send_audit(self.bot, guild, embed, fallback_channel_id=channel_id)

    # ── Messages ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if guild is None:
            return
        message = payload.cached_message
        if message is not None and message.author.bot:
            return
        if not claim_side_effect(f"messageDelete:{guild.id}:{payload.message_id}"):
            return

        if message is not None and (message.content or message.attachments):
            self.snipes.add(
                payload.channel_id,
                DeletedMessage(
                    author_name=message.author.name,
                    author_avatar=message.author.display_avatar.url,
                    content=message.content,
                    attachment_url=message.attachments[0].url if message.attachments else None,
                    deleted_at=discord.utils.utcnow(),
                    stored_at=time.monotonic(),
                ),
            )

        embed = discord.Embed(color=ERROR, title="🗑️ Mensaje eliminado", timestamp=discord.utils.utcnow())
        author = message.author if message else None
        embed.set_author(
            name=author.name if author else "Usuario desconocido",
            icon_url=author.display_avatar.url if author else None,
        )
        embed.add_field(name="📢 Canal", value=f"<#{payload.channel_id}>", inline=True)
        embed.add_field(name="👤 Autor", value=author.mention if author else "Desconocido", inline=True)
        embed.add_field(
            name="📝 Contenido",
            value=truncate(message.content, 1024) if message and message.content else "*Sin contenido de texto*",
            inline=False,
        )
        if message and message.attachments:
            urls = "\n".join(a.url for a in message.attachments)
            embed.add_field(name="📎 Adjuntos", value=truncate(urls, 1024), inline=False)
        embed.set_footer(text=f"ID del mensaje: {payload.message_id}")

        config = await self.bot.configs.get(guild.id)
        sent = await send_to(guild, config.message_log_channel_id, embed=embed)
        await send_audit(self.bot, guild, embed, already_sent=[sent.channel.id if sent else None])

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if guild is None:
            return
        new_content = payload.data.get("content")
        author_data = payload.data.get("author") or {}
        if author_data.get("bot") or new_content is None:
            return
        before = payload.cached_message
        if before is not None and before.content == new_content:
            return
        edited = payload.data.get("edited_timestamp") or "0"
        if not claim_side_effect(f"messageUpdate:{guild.id}:{payload.message_id}:{edited}"):
            return

        member = guild.get_member(int(author_data["id"])) if author_data.get("id") else None
        embed = discord.Embed(color=WARN, title="✏️ Mensaje editado", timestamp=discord.utils.utcnow())
        embed.set_author(
            name=member.name if member else author_data.get("username", "Usuario desconocido"),
            icon_url=member.display_avatar.url if member else None,
        )
        embed.add_field(name="📢 Canal", value=f"<#{payload.channel_id}>", inline=True)
        embed.add_field(
            name="👤 Autor", value=f"<@{author_data['id']}>" if author_data.get("id") else "Desconocido", inline=True
        )
        embed.add_field(
            name="📝 Antes",
            value=truncate(before.content, 1024) if before and before.content else "*Sin contenido guardado*",
            inline=False,
        )
        embed.add_field(name="📝 Despues", value=truncate(new_content, 1024) or "*Sin contenido de texto*", inline=False)
        embed.set_footer(text=f"ID: {payload.message_id}")

        config = await self.bot.configs.get(guild.id)
        sent = await send_to(guild, config.message_log_channel_id, embed=embed)
        await send_audit(self.bot, guild, embed, already_sent=[sent.channel.id if sent else None])

    # ── Channels ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        log_id = await self._audit_channel_id(channel.guild)
        if not log_id:
            return
        executor = await audit_executor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        embed = discord.Embed(color=OK, title="Canal creado", timestamp=discord.utils.utcnow())
        embed.add_field(name="Nombre", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Tipo", value=CHANNEL_TYPE_NAMES.get(channel.type, "Desconocido"), inline=True)
        embed.add_field(name="Categoria", value=channel.category.name if channel.category else "Ninguna", inline=True)
        embed.add_field(name="Ejecutor", value=executor, inline=True)
        embed.set_footer(text=f"ID del canal: {channel.id}")
        await self._audit(channel.guild, embed, log_id)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        log_id = await self._audit_channel_id(channel.guild)
        if not log_id:
            return
        executor = await audit_executor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        embed = discord.Embed(color=ERROR, title="Canal eliminado", timestamp=discord.utils.utcnow())
        embed.add_field(name="Nombre", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Tipo", value=CHANNEL_TYPE_NAMES.get(channel.type, "Desconocido"), inline=True)
        embed.add_field(name="Ejecutor", value=executor, inline=True)
        embed.set_footer(text=f"ID del canal: {channel.id}")
        await self._audit(channel.guild, embed, log_id)

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel
    ) -> None:
        log_id = await self._audit_channel_id(after.guild)
        if not log_id:
            return
        changes = []
        if before.name != after.name:
            changes.append(f"**Nombre:** `{before.name}` → `{after.name}`")
        if before.category_id != after.category_id:
            changes.append(
                f"**Categoria:** {before.category.name if before.category else 'Ninguna'} → "
                f"{after.category.name if after.category else 'Ninguna'}"
            )
        if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
            if before.topic != after.topic:
                changes.append(
                    f"**Tema:** {truncate_audit_value(before.topic, 100)} -> {truncate_audit_value(after.topic, 100)}"
                )
            if before.nsfw != after.nsfw:
                changes.append(f"**NSFW:** {before.nsfw} → {after.nsfw}")
            if before.slowmode_delay != after.slowmode_delay:
                changes.append(f"**Modo lento:** {before.slowmode_delay}s → {after.slowmode_delay}s")
        if not changes:
            return
        executor = await audit_executor(after.guild, discord.AuditLogAction.channel_update, after.id)
        embed = discord.Embed(color=WARN, title="Canal actualizado", timestamp=discord.utils.utcnow())
        embed.add_field(name="Canal", value=f"<#{after.id}> ({after.name})", inline=True)
        embed.add_field(name="Ejecutor", value=executor, inline=True)
        embed.add_field(name="Cambios", value="\n".join(changes)[:1024], inline=False)
        embed.set_footer(text=f"ID del canal: {after.id}")
        await self._audit(after.guild, embed, log_id)

    # ── Roles ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        log_id = await self._audit_channel_id(role.guild)
        if not log_id:
            return
        executor = await audit_executor(role.guild, discord.AuditLogAction.role_create, role.id)
        embed = discord.Embed(color=role.color.value or OK, title="Rol creado", timestamp=discord.utils.utcnow())
        embed.add_field(name="Nombre", value=role.name, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Mencionable", value="Si" if role.mentionable else "No", inline=True)
        embed.add_field(name="Separado", value="Si" if role.hoist else "No", inline=True)
        embed.add_field(name="Ejecutor", value=executor, inline=True)
        embed.set_footer(text=f"ID del rol: {role.id}")
        await self._audit(role.guild, embed, log_id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        log_id = await self._audit_channel_id(role.guild)
        if not log_id:
            return
        executor = await audit_executor(role.guild, discord.AuditLogAction.role_delete, role.id)
        embed = discord.Embed(color=ERROR, title="Rol eliminado", timestamp=discord.utils.utcnow())
        embed.add_field(name="Nombre", value=role.name, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Miembros", value=str(len(role.members)), inline=True)
        embed.add_field(name="Ejecutor", value=executor, inline=True)
        embed.set_footer(text=f"ID del rol: {role.id}")
        await self._audit(role.guild, embed, log_id)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        log_id = await self._audit_channel_id(after.guild)
        if not log_id:
            return
        changes = []
        if before.name != after.name:
            changes.append(f"**Nombre:** `{before.name}` → `{after.name}`")
        if before.color != after.color:
            changes.append(f"**Color:** {before.color} → {after.color}")
        if before.hoist != after.hoist:
            changes.append(f"**Separado:** {before.hoist} → {after.hoist}")
        if before.mentionable != after.mentionable:
            changes.append(f"**Mencionable:** {before.mentionable} → {after.mentionable}")
        if before.permissions != after.permissions:
            changes.append("**Permisos cambiados**")
        if not changes:
            return
        executor = await audit_executor(after.guild, discord.AuditLogAction.role_update, after.id)
        embed = discord.Embed(color=after.color.value or WARN, title="Rol actualizado", timestamp=discord.utils.utcnow())
        embed.add_field(name="Rol", value=f"{after.mention} ({after.name})", inline=True)
        embed.add_field(name="Ejecutor", value=executor, inline=True)
        embed.add_field(name="Cambios", value="\n".join(changes), inline=False)
        embed.set_footer(text=f"ID del rol: {after.id}")
        await self._audit(after.guild, embed, log_id)

    # ── Members ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        log_id = await self._audit_channel_id(after.guild)
        if not log_id:
            return
        added = [r for r in after.roles if r not in before.roles and not r.is_default()]
        removed = [r for r in before.roles if r not in after.roles and not r.is_default()]
        if added:
            embed = _member_embed(after, OK, "Roles agregados")
            embed.add_field(name="Usuario", value=after.mention, inline=True)
            embed.add_field(name="Roles agregados", value=", ".join(r.mention for r in added)[:1024], inline=True)
            await self._audit(after.guild, embed, log_id)
        if removed:
            embed = _member_embed(after, ERROR, "Roles removidos")
            embed.add_field(name="Usuario", value=after.mention, inline=True)
            embed.add_field(name="Roles removidos", value=", ".join(r.mention for r in removed)[:1024], inline=True)
            await self._audit(after.guild, embed, log_id)
        if before.nick != after.nick:
            embed = _member_embed(after, WARN, "Apodo cambiado")
            embed.add_field(name="Usuario", value=after.mention, inline=True)
            embed.add_field(name="Antes", value=before.nick or "*Ninguno*", inline=True)
            embed.add_field(name="Despues", value=after.nick or "*Ninguno*", inline=True)
            await self._audit(after.guild, embed, log_id)
        if not before.timed_out_until and after.timed_out_until:
            embed = _member_embed(after, PINK, "Miembro en timeout")
            embed.add_field(name="Usuario", value=after.mention, inline=True)
            embed.add_field(name="Hasta", value=discord_ts(after.timed_out_until), inline=True)
            await self._audit(after.guild, embed, log_id)
        elif before.timed_out_until and not after.timed_out_until:
            embed = _member_embed(after, OK, "Timeout removido")
            embed.add_field(name="Usuario", value=after.mention, inline=True)
            await self._audit(after.guild, embed, log_id)

    # ── Voice ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if member.bot:
            return
        log_id = await self._audit_channel_id(member.guild, voice=True)
        if not log_id:
            return
        old, new = before.channel, after.channel
        if old is None and new is not None:
            embed = _member_embed(member, OK, "Se unio a un canal de voz")
            embed.add_field(name="Usuario", value=member.mention, inline=True)
            embed.add_field(name="Canal", value=new.mention, inline=True)
            await self._audit(member.guild, embed, log_id)
        elif old is not None and new is None:
            embed = _member_embed(member, ERROR, "Salio de un canal de voz")
            embed.add_field(name="Usuario", value=member.mention, inline=True)
            embed.add_field(name="Canal", value=old.mention, inline=True)
            await self._audit(member.guild, embed, log_id)
        elif old is not None and new is not None and old.id != new.id:
            embed = _member_embed(member, WARN, "Se movio entre canales de voz")
            embed.add_field(name="Usuario", value=member.mention, inline=True)
            embed.add_field(name="De", value=old.mention, inline=True)
            embed.add_field(name="A", value=new.mention, inline=True)
            await self._audit(member.guild, embed, log_id)

        where = new.mention if new else "Ninguno"
        if before.mute != after.mute:
            title = "Silenciado por el servidor" if after.mute else "Silencio del servidor quitado"
            embed = _member_embed(member, PINK, title)
            embed.add_field(name="Usuario", value=member.mention, inline=True)
            embed.add_field(name="Canal", value=where, inline=True)
            await self._audit(member.guild, embed, log_id)
        if before.deaf != after.deaf:
            title = "Enmudecido por el servidor" if after.deaf else "Enmudecimiento del servidor quitado"
            embed = _member_embed(member, PINK, title)
            embed.add_field(name="Usuario", value=member.mention, inline=True)
            embed.add_field(name="Canal", value=where, inline=True)
            await self._audit(member.guild, embed, log_id)

    # ── /snipe ───────────────────────────────────────────────────────────

    @app_commands.command(name="snipe", description="Ver el último mensaje eliminado en un canal",
                          extras={"module": "utility", "cooldown": 5, "permissions": ["manage_messages"]})
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(
        indice="Qué mensaje eliminado ver (1 = más reciente, hasta 10)",
        canal="Canal del que recuperar (por defecto el actual)",
    )
    async def snipe(
        self,
        interaction: discord.Interaction,
        indice: app_commands.Range[int, 1, 10] = 1,
        canal: discord.TextChannel | None = None,
    ) -> None:
        channel_id = canal.id if canal else interaction.channel_id
        stack = self.snipes.items(channel_id or 0)
        if indice > len(stack):
            await interaction.response.send_message(
                "Nada que recuperar — no hay mensajes eliminados recientemente en este canal.", ephemeral=True
            )
            return
        item = stack[indice - 1]
        embed = discord.Embed(
            color=module_color("utility"),
            description=item.content or "*Sin contenido de texto*",
            timestamp=item.deleted_at,
        )
        embed.set_author(name=item.author_name, icon_url=item.author_avatar)
        embed.set_footer(text=f"{indice}/{len(stack)} • Eliminado")
        if item.attachment_url:
            embed.set_image(url=item.attachment_url)
        await interaction.response.send_message(embed=embed)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(ServerLogs(bot))
