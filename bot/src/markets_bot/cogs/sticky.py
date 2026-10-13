"""Sticky messages (``/fijo``, ``/hablar fijo:true``): kept as the last message of a channel."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Any

import aiohttp
import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from markets_bot.bot import MarketsBot
from markets_bot.core.pipeline import MessagePipeline
from markets_bot.core.tasks import resilient
from markets_bot.core.utils import INFO, parse_color, utcnow
from markets_bot.db.models import GuildConfig, ScheduledMessage, StickyMessage
from markets_bot.web.internal_server import HttpError, json_response, read_json

log = logging.getLogger(__name__)

RESEND_COOLDOWN = 0.75  # seconds; coalesces bursts while keeping the sticky visibly at the bottom
EMPTY = "​"
EVERY_PREFIX = "@every:"
INTERVAL_UNITS = {"minutos": 60_000, "horas": 3_600_000, "dias": 86_400_000}
UNIT_LABELS = {"minutos": ("minuto", "minutos"), "horas": ("hora", "horas"), "dias": ("día", "días")}
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


# Guild channels the bot can post in (text, threads, and text-in-voice).
GUILD_TEXT = (discord.TextChannel, discord.Thread, discord.VoiceChannel)

class Sticky(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self._channels: set[str] = set()
        self._locks: dict[int, asyncio.Lock] = {}
        self._last_resend: dict[int, float] = {}
        self._trailing: dict[int, asyncio.TimerHandle] = {}
        bot.pipeline.register("sticky", self.on_channel_message, MessagePipeline.STICKY, include_bots=True)
        bot.internal.route("POST", "/internal/sticky/resend")(self._resend_route)
        bot.internal.route("POST", "/internal/sticky/remove")(self._remove_route)

    async def cog_load(self) -> None:
        self.refresh_cache.start()

    async def cog_unload(self) -> None:
        self.refresh_cache.cancel()
        for handle in self._trailing.values():
            handle.cancel()

    @tasks.loop(seconds=60)
    @resilient
    async def refresh_cache(self) -> None:
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(StickyMessage.channel_id).where(
                StickyMessage.enabled.is_(True), StickyMessage.guild_id.in_(guild_ids)))).scalars().all()
        self._channels = set(rows)

    @refresh_cache.before_loop
    async def _wait(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_cache_invalidate(self, guild_id: str | None) -> None:
        await self.refresh_cache.coro(self)

    # ── Reposting ────────────────────────────────────────────────────────

    async def on_channel_message(self, message: discord.Message, config: GuildConfig) -> None:
        channel = message.channel
        if str(channel.id) not in self._channels:
            return
        lock = self._locks.setdefault(channel.id, asyncio.Lock())
        if lock.locked():
            if message.author.id != self.bot.user.id:  # type: ignore[union-attr]
                self._schedule_trailing(channel, RESEND_COOLDOWN)
            return
        remaining = RESEND_COOLDOWN - (time.monotonic() - self._last_resend.get(channel.id, 0))
        if remaining > 0:
            self._schedule_trailing(channel, remaining)
            return
        await self._resend(channel, skip_message_id=message.id)

    def _schedule_trailing(self, channel: discord.abc.Messageable, delay: float) -> None:
        cid = channel.id  # type: ignore[attr-defined]
        if handle := self._trailing.pop(cid, None):
            handle.cancel()

        def fire() -> None:
            self._trailing.pop(cid, None)
            self.bot.spawn(self._resend(channel), name=f"sticky-{cid}")

        self._trailing[cid] = asyncio.get_running_loop().call_later(max(0.1, delay), fire)

    async def _files(self, sticky: StickyMessage, old: discord.Message | None) -> list[discord.File]:
        """Re-upload attachments. Reading them from the live message avoids expired CDN links."""
        files: list[discord.File] = []
        if old is not None and old.attachments:
            for att in old.attachments:
                try:
                    files.append(await att.to_file())
                except discord.HTTPException:
                    continue
            return files
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as http:
            for index, url in enumerate(sticky.attachment_urls or []):
                try:
                    async with http.get(url) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.content.read(MAX_ATTACHMENT_BYTES + 1)
                except (aiohttp.ClientError, TimeoutError):
                    continue
                if len(data) <= MAX_ATTACHMENT_BYTES:
                    name = url.split("?")[0].rsplit("/", 1)[-1] or f"imagen-{index + 1}.png"
                    files.append(discord.File(io.BytesIO(data), filename=name))
        return files

    async def _resend(self, channel: discord.abc.Messageable, *, skip_message_id: int | None = None,
                      mention_everyone: bool = False, allow_mentions: bool = False) -> bool:
        cid = channel.id  # type: ignore[attr-defined]
        lock = self._locks.setdefault(cid, asyncio.Lock())
        async with lock:
            self._last_resend[cid] = time.monotonic()
            async with self.bot.db.session() as session:
                sticky = (await session.execute(select(StickyMessage).where(
                    StickyMessage.channel_id == str(cid)))).scalar_one_or_none()
            if sticky is None or not sticky.enabled:
                self._channels.discard(str(cid))
                return False
            if skip_message_id is not None and sticky.message_id == str(skip_message_id):
                return False  # the current sticky itself: avoid self-repost loops
            old = None
            if sticky.message_id:
                try:
                    old = await channel.fetch_message(int(sticky.message_id))
                except discord.HTTPException:
                    old = None
            kwargs: dict[str, Any] = {
                "files": await self._files(sticky, old),
                "allowed_mentions": discord.AllowedMentions(everyone=mention_everyone, roles=allow_mentions,
                                                            users=allow_mentions),
            }
            if sticky.plain_text:
                body = "" if sticky.description == EMPTY else sticky.description
                kwargs["content"] = (f"@everyone\n{body}" if body else "@everyone") if mention_everyone else (body or None)
            else:
                embed = discord.Embed(color=parse_color(sticky.color, INFO))
                if sticky.title:
                    embed.title = sticky.title
                if sticky.description:
                    embed.description = sticky.description
                kwargs["embed"] = embed
                kwargs["content"] = "@everyone" if mention_everyone else None
            try:
                sent = await channel.send(**kwargs)  # send first so attachments stay readable
            except discord.HTTPException as exc:
                log.error("Error re-sending sticky in %s: %s", cid, exc)
                return False
            if old is not None:
                try:
                    await old.delete()
                except discord.HTTPException:
                    pass
            async with self.bot.db.session() as session:
                await session.execute(update(StickyMessage).where(StickyMessage.channel_id == str(cid)).values(
                    message_id=str(sent.id), attachment_urls=[a.url for a in sent.attachments]))
            self._channels.add(str(cid))
            return True

    # ── /fijo ────────────────────────────────────────────────────────────

    fijo = app_commands.Group(name="fijo", description="Gestionar mensajes fijos que se mantienen al final del canal",
                              guild_only=True, default_permissions=discord.Permissions(manage_messages=True),
                              extras={"module": "sticky", "cooldown": 5})

    @fijo.command(name="establecer", description="Establecer un mensaje fijo en este canal")
    @app_commands.describe(titulo="Título del embed", descripcion="Descripción / contenido del embed",
                           color="Color hex del embed (ej. #5865F2)", canal="Canal (por defecto el actual)")
    async def set_sticky(self, interaction: discord.Interaction, titulo: str, descripcion: str,
                         color: str = "#5865F2", canal: discord.TextChannel | None = None) -> None:
        channel = canal or interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("Canal inválido.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._upsert(interaction, channel, title=titulo, description=descripcion, color=color, plain=False, files=[])
        await self._resend(channel)
        await interaction.followup.send(f"Mensaje fijo establecido en <#{channel.id}>. Se mantendrá al final del canal.",  # type: ignore[attr-defined]
                                        ephemeral=True)
        log.info("%s set a sticky message in %s", interaction.user, channel.id)  # type: ignore[attr-defined]

    async def _upsert(self, interaction: discord.Interaction, channel: Any, *, title: str | None, description: str,
                      color: str, plain: bool, files: list[str]) -> None:
        values = {"title": title, "description": description, "color": color, "plainText": plain,
                  "attachmentUrls": files, "enabled": True, "createdBy": str(interaction.user.id), "updatedAt": utcnow()}
        async with self.bot.db.session() as session:
            await session.execute(insert(StickyMessage).values(
                guild_id=str(interaction.guild_id), channel_id=str(channel.id), title=title, description=description,
                color=color, plain_text=plain, attachment_urls=files, enabled=True, created_by=str(interaction.user.id),
            ).on_conflict_do_update(index_elements=["channelId"], set_=values))
        self._channels.add(str(channel.id))

    @fijo.command(name="quitar", description="Quitar el mensaje fijo de un canal")
    @app_commands.describe(canal="Canal (por defecto el actual)")
    async def remove_sticky(self, interaction: discord.Interaction, canal: discord.TextChannel | None = None) -> None:
        channel = canal or interaction.channel
        if channel is None:
            await interaction.response.send_message("Canal inválido.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        removed = await self.remove(channel.id)
        await interaction.followup.send(
            f"Mensaje fijo eliminado de <#{channel.id}>." if removed else f"No se encontró mensaje fijo en <#{channel.id}>.",
            ephemeral=True)

    async def remove(self, channel_id: int) -> bool:
        async with self.bot.db.session() as session:
            sticky = (await session.execute(select(StickyMessage).where(
                StickyMessage.channel_id == str(channel_id)))).scalar_one_or_none()
            if sticky is None:
                return False
            await session.execute(delete(StickyMessage).where(StickyMessage.id == sticky.id))
        self._channels.discard(str(channel_id))
        if handle := self._trailing.pop(channel_id, None):
            handle.cancel()
        channel = self.bot.get_channel(channel_id)
        if sticky.message_id and isinstance(channel, discord.abc.Messageable):
            try:
                await channel.get_partial_message(int(sticky.message_id)).delete()  # type: ignore[attr-defined]
            except discord.HTTPException:
                pass
        return True

    @fijo.command(name="lista", description="Listar todos los mensajes fijos del servidor")
    async def list_stickies(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(StickyMessage).where(StickyMessage.guild_id == str(interaction.guild_id))
                                          .order_by(StickyMessage.created_at.desc()))).scalars().all()
        if not rows:
            await interaction.response.send_message("No hay mensajes fijos configurados en este servidor.", ephemeral=True)
            return
        lines = [f"**{i}.** <#{s.channel_id}>\nTítulo: {s.title or 'Sin título'}\nEstado: {'Activo' if s.enabled else 'Desactivado'}"
                 for i, s in enumerate(rows, 1)]
        embed = discord.Embed(color=INFO, title="Mensajes Fijos", description="\n\n".join(lines)[:4096])
        embed.set_footer(text=f"{len(rows)} mensaje(s) fijo(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /hablar ──────────────────────────────────────────────────────────

    @app_commands.command(name="hablar", description="Hacer que el bot envíe un mensaje en un canal",
                          extras={"module": "utility", "cooldown": 5, "permissions": ["manage_messages"]})
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.describe(
        mensaje="El mensaje que dirá el bot", imagen1="Imagen 1 (opcional)", imagen2="Imagen 2 (opcional)",
        imagen3="Imagen 3 (opcional)", imagen4="Imagen 4 (opcional)", imagen5="Imagen 5 (opcional)",
        imagen6="Imagen 6 (opcional)", imagen7="Imagen 7 (opcional)", imagen8="Imagen 8 (opcional)",
        imagen9="Imagen 9 (opcional)", imagen10="Imagen 10 (opcional)",
        canal="Canal donde enviar el mensaje (por defecto el actual)",
        id_canal='ID del canal donde enviar el mensaje (tiene prioridad sobre "canal")',
        fijo="Mantener este mensaje siempre al final del canal", everyone="Mencionar a @everyone una vez al publicar",
        cada="Repetir automáticamente @everyone cada cierta cantidad",
        unidad="Unidad del intervalo automático (por defecto: horas)",
        detener_everyone="Detener el @everyone automático de este canal")
    @app_commands.choices(unidad=[app_commands.Choice(name="Minutos", value="minutos"),
                                  app_commands.Choice(name="Horas", value="horas"),
                                  app_commands.Choice(name="Días", value="dias")])
    async def speak(
        self, interaction: discord.Interaction, mensaje: app_commands.Range[str, 1, 2000] | None = None,
        imagen1: discord.Attachment | None = None, imagen2: discord.Attachment | None = None,
        imagen3: discord.Attachment | None = None, imagen4: discord.Attachment | None = None,
        imagen5: discord.Attachment | None = None, imagen6: discord.Attachment | None = None,
        imagen7: discord.Attachment | None = None, imagen8: discord.Attachment | None = None,
        imagen9: discord.Attachment | None = None, imagen10: discord.Attachment | None = None,
        canal: discord.TextChannel | None = None, id_canal: str | None = None, fijo: bool = False,
        everyone: bool = False, cada: app_commands.Range[int, 1, 43200] | None = None, unidad: str | None = None,
        detener_everyone: bool = False,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        attachments = [a for a in (imagen1, imagen2, imagen3, imagen4, imagen5, imagen6, imagen7, imagen8, imagen9,
                                   imagen10) if a]
        if id_canal:
            channel: Any = guild.get_channel(int(id_canal)) if id_canal.isdigit() else None
            if not isinstance(channel, GUILD_TEXT):
                await interaction.response.send_message(f"No encontré un canal de texto con la ID `{id_canal}`.",
                                                        ephemeral=True)
                return
        else:
            channel = canal or interaction.channel
        if not mensaje and not attachments and cada is None and not detener_everyone:
            await interaction.response.send_message(
                "Debes proporcionar un mensaje, una imagen, configurar un intervalo o detener el @everyone automático.",
                ephemeral=True)
            return
        if not isinstance(channel, GUILD_TEXT):
            await interaction.response.send_message("Canal inválido.", ephemeral=True)
            return
        if fijo and not mensaje and not attachments:
            await interaction.response.send_message(
                "Para dejar un mensaje fijo debes escribir un mensaje o adjuntar una imagen.", ephemeral=True)
            return
        if detener_everyone and cada is not None:
            await interaction.response.send_message(
                "No puedes programar y detener el @everyone automático al mismo tiempo.", ephemeral=True)
            return
        if unidad and cada is None:
            await interaction.response.send_message("Indica también la cantidad en la opción `cada`.", ephemeral=True)
            return
        if (everyone or cada is not None) and not interaction.permissions.mention_everyone:
            await interaction.response.send_message("Necesitas permiso para mencionar a @everyone.", ephemeral=True)
            return
        if (everyone or cada is not None) and not channel.permissions_for(guild.me).mention_everyone:
            await interaction.response.send_message(f"No tengo permiso para mencionar a @everyone en <#{channel.id}>.",
                                                    ephemeral=True)
            return
        expression = label = None
        if cada is not None:
            unit = unidad or "horas"
            ms = cada * INTERVAL_UNITS[unit]
            if ms < 15 * 60_000:
                await interaction.response.send_message("El intervalo mínimo es de 15 minutos.", ephemeral=True)
                return
            if ms > 30 * 86_400_000:
                await interaction.response.send_message("El intervalo máximo es de 30 días.", ephemeral=True)
                return
            expression = f"{EVERY_PREFIX}{ms}"
            label = f"{cada} {UNIT_LABELS[unit][0] if cada == 1 else UNIT_LABELS[unit][1]}"

        await interaction.response.defer(ephemeral=True)
        results: list[str] = []
        if mensaje or attachments:
            if fijo:
                await self._upsert(interaction, channel, title=None, description=mensaje or EMPTY, color="#5865F2",
                                   plain=True, files=[a.url for a in attachments])
                await self._resend(channel, mention_everyone=everyone, allow_mentions=True)
                results.append(f"Mensaje fijo publicado en <#{channel.id}> y protegido para volver siempre al final.")
            else:
                content = (f"@everyone\n{mensaje}" if mensaje else "@everyone") if everyone else mensaje
                files = [await a.to_file() for a in attachments]
                await channel.send(content=content, files=files, allowed_mentions=discord.AllowedMentions(
                    everyone=everyone, roles=True, users=True))
                results.append(f"Mensaje enviado a <#{channel.id}>.")

        async with self.bot.db.session() as session:
            existing = list((await session.execute(select(ScheduledMessage).where(
                ScheduledMessage.guild_id == str(guild.id), ScheduledMessage.channel_id == str(channel.id),
                ScheduledMessage.message == "@everyone", ScheduledMessage.cron.startswith(EVERY_PREFIX),
            ).order_by(ScheduledMessage.created_at))).scalars().all())
            if detener_everyone:
                if existing:
                    await session.execute(delete(ScheduledMessage).where(
                        ScheduledMessage.id.in_([s.id for s in existing])))
                    results.append(f"@everyone automático detenido en <#{channel.id}>.")
                else:
                    results.append(f"No había un @everyone automático activo en <#{channel.id}>.")
            if expression:
                if existing:
                    await session.execute(update(ScheduledMessage).where(ScheduledMessage.id == existing[0].id).values(
                        cron=expression, enabled=True))
                    if len(existing) > 1:
                        await session.execute(delete(ScheduledMessage).where(
                            ScheduledMessage.id.in_([s.id for s in existing[1:]])))
                else:
                    session.add(ScheduledMessage(guild_id=str(guild.id), channel_id=str(channel.id), message="@everyone",
                                                 cron=expression, enabled=True))
                results.append(f"@everyone automático configurado cada **{label}** en <#{channel.id}>.")
        await interaction.followup.send("\n".join(results), ephemeral=True)

    # ── Dashboard actions ────────────────────────────────────────────────

    async def _resend_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        channel = self.bot.get_channel(int(body.get("channelId") or 0))
        guild = getattr(channel, "guild", None)
        if not isinstance(channel, discord.abc.Messageable) or guild is None or str(guild.id) != str(body.get("guildId")):
            raise HttpError(404, "Canal no encontrado")
        ok = await self._resend(channel, mention_everyone=bool(body.get("mentionEveryone")),
                                allow_mentions=bool(body.get("allowMentions")))
        return json_response({"success": ok})

    async def _remove_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        return json_response({"success": await self.remove(int(body.get("channelId") or 0))})


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Sticky(bot))
