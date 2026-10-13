"""Automation: auto-responses, scheduled messages (cron or fixed interval) and polls."""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import aiohttp
import discord
from croniter import croniter
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import delete, select, update

from markets_bot.bot import MarketsBot
from markets_bot.core.cache import TtlCache
from markets_bot.core.pipeline import MessagePipeline
from markets_bot.core.tasks import resilient
from markets_bot.core.utils import INFO, OK, aware, discord_ts, module_color, parse_duration, utcnow
from markets_bot.db.models import AutoResponse, GuildConfig, Poll, ScheduledMessage

log = logging.getLogger(__name__)

EVERY_PREFIX = "@every:"
MIN_INTERVAL_MS = 15 * 60_000
MAX_INTERVAL_MS = 30 * 24 * 60 * 60_000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_EXT_RE = re.compile(r"\.(?:avif|gif|jpe?g|png|webp)$", re.IGNORECASE)
MATCH_CHOICES = [app_commands.Choice(name=n, value=v) for n, v in
                 (("Contiene", "contains"), ("Exacta", "exact"), ("Empieza con", "startsWith"), ("Regex", "regex"))]


# ─── Schedules ───────────────────────────────────────────────────────────────


def parse_every(expression: str) -> int | None:
    """``@every:<ms>`` (dashboard interval schedules) -> milliseconds."""
    if not expression.startswith(EVERY_PREFIX):
        return None
    raw = expression[len(EVERY_PREFIX):]
    if not raw.isdigit():
        return None
    ms = int(raw)
    return ms if MIN_INTERVAL_MS <= ms <= MAX_INTERVAL_MS else None


def normalize_cron(expression: str) -> str | None:
    """Validate a cron expression. node-cron's 6-field form (seconds first) is converted for croniter."""
    fields = expression.split()
    if len(fields) == 6:
        fields = [*fields[1:], fields[0]]
    candidate = " ".join(fields)
    return candidate if len(fields) in (5, 6) and croniter.is_valid(candidate) else None


def next_run(expression: str, after: datetime) -> datetime | None:
    every = parse_every(expression)
    if every is not None:
        return after + timedelta(milliseconds=every)
    cron = normalize_cron(expression)
    return croniter(cron, after).get_next(datetime) if cron else None


# ─── Polls ───────────────────────────────────────────────────────────────────


def poll_bar(percentage: float, length: int = 12) -> str:
    filled = round(percentage / 100 * length)
    return "█" * filled + "░" * (length - filled)


def poll_embed(poll: Poll, ended: bool = False) -> discord.Embed:
    votes = poll.votes or {}
    total = sum(len(v) for v in votes.values())
    winner = -1
    if ended and total:
        best = 0
        for i in range(len(poll.options)):
            count = len(votes.get(str(i), []))
            if count > best:
                best, winner = count, i
    lines = []
    for i, option in enumerate(poll.options):
        count = len(votes.get(str(i), []))
        pct = round(count / total * 100) if total else 0
        lines.append(f"**{i + 1}.** {option}{' 🏆' if ended and i == winner else ''}\n`{poll_bar(pct)}` **{pct}%** · "
                     f"{count} voto{'' if count == 1 else 's'}")
    timestamp = discord.utils.utcnow() if ended else aware(poll.ends_at) if poll.ends_at else None
    embed = discord.Embed(color=OK if ended else INFO, title=poll.question, description="\n\n".join(lines)[:4096],
                          timestamp=timestamp)
    embed.set_author(name="📊 Encuesta finalizada" if ended else "📊 Encuesta activa")
    embed.add_field(name="🗳️ Votos", value=f"**{total}**", inline=True)
    embed.add_field(name="👤 Creada por", value=f"<@{poll.creator_id}>", inline=True)
    embed.add_field(name="🏁 Estado" if ended else "⏳ Termina", inline=True,
                    value="**Finalizada**" if ended else discord_ts(poll.ends_at) if poll.ends_at else "**Sin límite**")
    roles = poll.allowed_role_ids or []
    embed.add_field(name="🔒 Puede votar", value=", ".join(f"<@&{r}>" for r in roles) if roles else "Todos", inline=False)
    embed.set_footer(text=f"ID: {poll.id[:8]}")
    return embed


def poll_view(poll: Poll) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for i, option in enumerate(poll.options[:25]):
        view.add_item(discord.ui.Button(custom_id=f"poll_{poll.id}_{i}", label=f"{i + 1}. {option[:77]}",
                                        style=discord.ButtonStyle.secondary, row=i // 5))
    return view


class Automation(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self._responses: TtlCache[list[AutoResponse]] = TtlCache(60, 1_000)
        self._next_due: dict[str, tuple[str, datetime]] = {}
        self._started = utcnow()
        bot.router.prefix("button", "poll_", self.on_vote)
        bot.pipeline.register("auto_responses", self.auto_respond, MessagePipeline.AUTORESPONSES)

    async def cog_load(self) -> None:
        self.scheduler.start()
        self.end_polls.start()

    async def cog_unload(self) -> None:
        self.scheduler.cancel()
        self.end_polls.cancel()

    @commands.Cog.listener()
    async def on_cache_invalidate(self, guild_id: str | None) -> None:
        if guild_id:
            self._responses.delete(guild_id)
        else:
            self._responses.clear()

    # ── Auto-responses ───────────────────────────────────────────────────

    async def _guild_responses(self, guild_id: str) -> list[AutoResponse]:
        cached = self._responses.get(guild_id)
        if cached is not None:
            return cached
        async with self.bot.db.session() as session:
            rows = list((await session.execute(select(AutoResponse).where(
                AutoResponse.guild_id == guild_id, AutoResponse.enabled.is_(True)))).scalars().all())
        self._responses.set(guild_id, rows)
        return rows

    @staticmethod
    def _matches(response: AutoResponse, content: str) -> bool:
        text, trigger = content.lower(), response.trigger.lower()
        if response.match_type == "exact":
            return text == trigger
        if response.match_type == "startsWith":
            return text.startswith(trigger)
        if response.match_type == "regex":
            if len(response.trigger) > 200:  # keep admin-provided patterns small
                return False
            try:
                return re.search(response.trigger, content, re.IGNORECASE) is not None
            except re.error:
                return False
        return trigger in text

    async def auto_respond(self, message: discord.Message, config: GuildConfig) -> None:
        if not config.automation_enabled or message.guild is None:
            return
        for response in await self._guild_responses(str(message.guild.id)):
            if not self._matches(response, message.content):
                continue
            text = (response.response.replace("{user}", message.author.mention)
                    .replace("{username}", message.author.name).replace("{server}", message.guild.name)
                    .replace("{channel}", f"<#{message.channel.id}>"))
            try:
                image = await self._download_image(text.strip())
                if image is not None:
                    await message.channel.send(file=image)
                else:
                    await message.channel.send(text)
            except discord.HTTPException as exc:
                log.error("Failed to send auto-response: %s", exc)
            return  # only the first match fires

    @staticmethod
    async def _download_image(url: str) -> discord.File | None:
        """Responses that are just an image URL are sent as an attachment (falls back to the link)."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or " " in url or not IMAGE_EXT_RE.search(parts.path):
            return None
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http, http.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.content.read(MAX_IMAGE_BYTES + 1)
        except (aiohttp.ClientError, TimeoutError):
            return None
        if len(data) > MAX_IMAGE_BYTES:
            return None
        ext = parts.path.rsplit(".", 1)[-1].lower()
        return discord.File(io.BytesIO(data), filename=f"respuesta-automatica.{ext}")

    autorespuesta = app_commands.Group(
        name="autorespuesta", description="Gestionar autorespuestas", guild_only=True,
        default_permissions=discord.Permissions(manage_messages=True),
        extras={"module": "automation", "cooldown": 5, "permissions": ["manage_messages"]})

    async def _find_response(self, guild_id: int, prefix: str) -> AutoResponse | None:
        async with self.bot.db.session() as session:
            return (await session.execute(select(AutoResponse).where(
                AutoResponse.guild_id == str(guild_id), AutoResponse.id.startswith(prefix)).limit(1))).scalar_one_or_none()

    @autorespuesta.command(name="agregar", description="Agregar una autorespuesta")
    @app_commands.describe(disparador="Palabra o frase disparadora", respuesta="Mensaje de respuesta",
                           coincidencia="Tipo de coincidencia")
    @app_commands.choices(coincidencia=MATCH_CHOICES)
    async def ar_add(self, interaction: discord.Interaction, disparador: str, respuesta: str,
                     coincidencia: str = "contains") -> None:
        item = AutoResponse(guild_id=str(interaction.guild_id), trigger=disparador, response=respuesta,
                            match_type=coincidencia)
        async with self.bot.db.session() as session:
            session.add(item)
        self._responses.delete(str(interaction.guild_id))
        embed = discord.Embed(color=module_color("automation"), title="Autorespuesta Creada", timestamp=discord.utils.utcnow())
        embed.add_field(name="Disparador", value=f"`{disparador}`", inline=True)
        embed.add_field(name="Tipo de coincidencia", value=coincidencia, inline=True)
        embed.add_field(name="Respuesta", value=respuesta[:1024], inline=False)
        embed.add_field(name="ID", value=f"`{item.id[:8]}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @autorespuesta.command(name="lista", description="Listar todas las autorespuestas")
    async def ar_list(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(AutoResponse).where(
                AutoResponse.guild_id == str(interaction.guild_id)).order_by(AutoResponse.created_at.desc()))).scalars().all()
        if not rows:
            await interaction.response.send_message("No hay autorespuestas configuradas.", ephemeral=True)
            return
        lines = [f"**{i}.** `{r.id[:8]}` {'✅' if r.enabled else '❌'} — **{r.match_type}:** `{r.trigger}`\n   → "
                 f"{r.response[:80]}{'...' if len(r.response) > 80 else ''}" for i, r in enumerate(rows, 1)]
        embed = discord.Embed(color=module_color("automation"), title="Autorespuestas", description="\n\n".join(lines)[:4096],
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"{len(rows)} autorespuesta(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @autorespuesta.command(name="eliminar", description="Eliminar una autorespuesta")
    @app_commands.describe(id="ID de la autorespuesta")
    async def ar_delete(self, interaction: discord.Interaction, id: str) -> None:
        item = await self._find_response(interaction.guild_id or 0, id)
        if item is None:
            await interaction.response.send_message("Autorespuesta no encontrada.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            await session.execute(delete(AutoResponse).where(AutoResponse.id == item.id))
        self._responses.delete(str(interaction.guild_id))
        await interaction.response.send_message(f"Autorespuesta `{item.trigger}` eliminada.", ephemeral=True)

    @autorespuesta.command(name="alternar", description="Activar o desactivar una autorespuesta")
    @app_commands.describe(id="ID de la autorespuesta")
    async def ar_toggle(self, interaction: discord.Interaction, id: str) -> None:
        item = await self._find_response(interaction.guild_id or 0, id)
        if item is None:
            await interaction.response.send_message("Autorespuesta no encontrada.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            await session.execute(update(AutoResponse).where(AutoResponse.id == item.id).values(enabled=not item.enabled))
        self._responses.delete(str(interaction.guild_id))
        await interaction.response.send_message(
            f"La autorespuesta `{item.trigger}` ahora esta **{'activada' if not item.enabled else 'desactivada'}**.",
            ephemeral=True)

    # ── Scheduled messages ───────────────────────────────────────────────

    @tasks.loop(seconds=20)
    @resilient
    async def scheduler(self) -> None:
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(ScheduledMessage).where(
                ScheduledMessage.guild_id.in_(guild_ids), ScheduledMessage.enabled.is_(True)))).scalars().all()
        now = utcnow()
        alive = set()
        for row in rows:
            alive.add(row.id)
            known = self._next_due.get(row.id)
            if known is None or known[0] != row.cron:
                # Interval schedules continue from the last run; cron schedules never "catch up" after downtime.
                base = (row.last_run or self._started) if parse_every(row.cron) is not None else now
                due = next_run(row.cron, base)
                if due is None:
                    log.warning("Invalid schedule for message %s: %s", row.id, row.cron)
                    self._next_due[row.id] = (row.cron, datetime.max)
                    continue
                self._next_due[row.id] = (row.cron, due)
            if self._next_due[row.id][1] <= now:
                await self._deliver(row)
                self._next_due[row.id] = (row.cron, next_run(row.cron, now) or datetime.max)
        for stale in set(self._next_due) - alive:
            del self._next_due[stale]

    async def _deliver(self, row: ScheduledMessage) -> None:
        channel = self.bot.get_channel(int(row.channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            return
        mentions_everyone = "@everyone" in row.message or "@here" in row.message
        try:
            await channel.send(row.message, allowed_mentions=discord.AllowedMentions(
                everyone=mentions_everyone, roles=True, users=True))
        except discord.HTTPException as exc:
            log.error("Error sending scheduled message %s: %s", row.id, exc)
            return
        async with self.bot.db.session() as session:
            await session.execute(update(ScheduledMessage).where(ScheduledMessage.id == row.id).values(last_run=utcnow()))

    programar = app_commands.Group(
        name="programar", description="Gestionar mensajes programados", guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
        extras={"module": "automation", "cooldown": 5, "permissions": ["manage_guild"]})

    async def _find_schedule(self, guild_id: int, prefix: str) -> ScheduledMessage | None:
        async with self.bot.db.session() as session:
            return (await session.execute(select(ScheduledMessage).where(
                ScheduledMessage.guild_id == str(guild_id), ScheduledMessage.id.startswith(prefix)).limit(1)
            )).scalar_one_or_none()

    @programar.command(name="agregar", description="Agregar un mensaje programado")
    @app_commands.describe(cron='Expresion cron (ej. "0 9 * * *" para diario a las 9am)', mensaje="Mensaje a enviar",
                           canal="Canal donde enviar")
    async def sched_add(self, interaction: discord.Interaction, cron: str, mensaje: str, canal: discord.TextChannel) -> None:
        if normalize_cron(cron) is None:
            await interaction.response.send_message(
                "Expresion cron invalida. Ejemplos:\n`0 9 * * *` — todos los dias a las 9:00 AM\n`0 */6 * * *` — cada 6 "
                "horas\n`0 0 * * 1` — cada lunes a medianoche", ephemeral=True)
            return
        row = ScheduledMessage(guild_id=str(interaction.guild_id), channel_id=str(canal.id), message=mensaje, cron=cron,
                               enabled=True)
        async with self.bot.db.session() as session:
            session.add(row)
        embed = discord.Embed(color=module_color("automation"), title="Mensaje Programado Creado",
                              timestamp=discord.utils.utcnow())
        embed.add_field(name="ID", value=f"`{row.id[:8]}`", inline=True)
        embed.add_field(name="Canal", value=canal.mention, inline=True)
        embed.add_field(name="Cron", value=f"`{cron}`", inline=True)
        embed.add_field(name="Mensaje", value=mensaje[:1024], inline=False)
        embed.set_footer(text="La tarea se ejecutara dentro de 5 minutos")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @programar.command(name="lista", description="Listar todos los mensajes programados")
    async def sched_list(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(ScheduledMessage).where(
                ScheduledMessage.guild_id == str(interaction.guild_id)).order_by(ScheduledMessage.created_at.desc()))).scalars().all()
        if not rows:
            await interaction.response.send_message("No hay mensajes programados.", ephemeral=True)
            return
        lines = []
        for i, s in enumerate(rows, 1):
            line = (f"**{i}.** `{s.id[:8]}` {'✅' if s.enabled else '❌'}\n   Canal: <#{s.channel_id}> | Cron: `{s.cron}`\n"
                    f"   Mensaje: {s.message[:60]}{'...' if len(s.message) > 60 else ''}")
            if s.last_run:
                line += f"\n   Ultima ejecucion: {discord_ts(s.last_run)}"
            lines.append(line)
        await interaction.response.send_message(embed=discord.Embed(
            color=module_color("automation"), title="Mensajes Programados", description="\n\n".join(lines)[:4096],
            timestamp=discord.utils.utcnow()), ephemeral=True)

    @programar.command(name="eliminar", description="Eliminar un mensaje programado")
    @app_commands.describe(id="ID del mensaje programado")
    async def sched_delete(self, interaction: discord.Interaction, id: str) -> None:
        row = await self._find_schedule(interaction.guild_id or 0, id)
        if row is None:
            await interaction.response.send_message("Mensaje programado no encontrado.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            await session.execute(delete(ScheduledMessage).where(ScheduledMessage.id == row.id))
        await interaction.response.send_message(f"Mensaje programado `{row.id[:8]}` eliminado.", ephemeral=True)

    @programar.command(name="alternar", description="Activar o desactivar un mensaje programado")
    @app_commands.describe(id="ID del mensaje programado")
    async def sched_toggle(self, interaction: discord.Interaction, id: str) -> None:
        row = await self._find_schedule(interaction.guild_id or 0, id)
        if row is None:
            await interaction.response.send_message("Mensaje programado no encontrado.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            await session.execute(update(ScheduledMessage).where(ScheduledMessage.id == row.id).values(enabled=not row.enabled))
        await interaction.response.send_message(
            f"El mensaje programado `{row.id[:8]}` ahora esta **{'activado' if not row.enabled else 'desactivado'}**.",
            ephemeral=True)

    # ── Polls ────────────────────────────────────────────────────────────

    async def on_vote(self, interaction: discord.Interaction) -> None:
        parts = str((interaction.data or {}).get("custom_id", "")).split("_")
        if len(parts) < 3 or not parts[2].isdigit():
            return
        poll_id, option = parts[1], int(parts[2])
        async with self.bot.db.session() as session:
            poll = await session.get(Poll, poll_id, with_for_update=True)
            if poll is None:
                await interaction.response.send_message("Esta encuesta ya no existe.", ephemeral=True)
                return
            if poll.ended:
                await interaction.response.send_message("Esta encuesta ya terminó.", ephemeral=True)
                return
            if poll.ends_at and utcnow() > poll.ends_at:
                await interaction.response.send_message("Esta encuesta ha expirado.", ephemeral=True)
                return
            allowed = poll.allowed_role_ids or []
            if allowed:
                member = interaction.user
                roles = {str(r.id) for r in member.roles} if isinstance(member, discord.Member) else set()
                if not roles & set(allowed):
                    await interaction.response.send_message(
                        f"❌ Solo pueden votar los miembros con los roles: {', '.join(f'<@&{r}>' for r in allowed)}",
                        ephemeral=True)
                    return
            user_id = str(interaction.user.id)
            votes = {k: [u for u in v if u != user_id] for k, v in (poll.votes or {}).items()}
            if user_id not in (poll.votes or {}).get(str(option), []):
                votes.setdefault(str(option), []).append(user_id)
            poll.votes = votes
        await interaction.response.edit_message(embed=poll_embed(poll))

    @tasks.loop(seconds=30)
    @resilient
    async def end_polls(self) -> None:
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        async with self.bot.db.session() as session:
            expired = (await session.execute(select(Poll).where(
                Poll.guild_id.in_(guild_ids), Poll.ended.is_(False), Poll.ends_at <= utcnow()))).scalars().all()
            for poll in expired:
                poll.ended = True
        for poll in expired:
            await self._close_poll_message(poll)
            log.info("Auto-ended poll %s — %s", poll.id, poll.question)

    async def _close_poll_message(self, poll: Poll) -> None:
        channel = self.bot.get_channel(int(poll.channel_id))
        if not isinstance(channel, discord.abc.Messageable) or not poll.message_id:
            return
        try:
            message = await channel.fetch_message(int(poll.message_id))
            await message.edit(embed=poll_embed(poll, ended=True), view=None)
        except discord.HTTPException:
            pass

    @scheduler.before_loop
    @end_polls.before_loop
    async def _wait(self) -> None:
        await self.bot.wait_until_ready()

    encuesta = app_commands.Group(name="encuesta", description="Crear y gestionar encuestas", guild_only=True,
                                  extras={"module": "automation", "cooldown": 10})

    @encuesta.command(name="crear", description="Crear una nueva encuesta")
    @app_commands.describe(pregunta="Pregunta de la encuesta", opciones="Opciones separadas por | (ej. Si | No | Tal vez)",
                           duracion="Duración (ej. 1h, 1d, 30m). Sin límite si se deja vacío",
                           mencionar="Mencionar antes de la encuesta", rol1="Rol que puede votar (dejar vacío = todos)",
                           rol2="Rol adicional que puede votar", rol3="Rol adicional que puede votar",
                           rol4="Rol adicional que puede votar", rol5="Rol adicional que puede votar")
    @app_commands.choices(mencionar=[app_commands.Choice(name="@everyone", value="@everyone"),
                                     app_commands.Choice(name="@here", value="@here"),
                                     app_commands.Choice(name="Ninguno", value="none")])
    async def poll_create(self, interaction: discord.Interaction, pregunta: str, opciones: str,
                          duracion: str | None = None, mencionar: str = "none", rol1: discord.Role | None = None,
                          rol2: discord.Role | None = None, rol3: discord.Role | None = None,
                          rol4: discord.Role | None = None, rol5: discord.Role | None = None) -> None:
        options = [o.strip() for o in opciones.split("|") if o.strip()]
        if not 2 <= len(options) <= 10:
            await interaction.response.send_message("Debes proporcionar entre 2 y 10 opciones, separadas por `|`.",
                                                    ephemeral=True)
            return
        seconds = parse_duration(duracion) if duracion else None
        poll = Poll(guild_id=str(interaction.guild_id), channel_id=str(interaction.channel_id), question=pregunta,
                    options=options, creator_id=str(interaction.user.id), votes={}, ended=False,
                    ends_at=utcnow() + timedelta(seconds=seconds) if seconds else None,
                    allowed_role_ids=[str(r.id) for r in (rol1, rol2, rol3, rol4, rol5) if r])
        async with self.bot.db.session() as session:
            session.add(poll)
        mention = mencionar if mencionar != "none" else None
        await interaction.response.send_message(content=mention, embed=poll_embed(poll), view=poll_view(poll),
                                                allowed_mentions=discord.AllowedMentions(everyone=bool(mention)))
        message = await interaction.original_response()
        async with self.bot.db.session() as session:
            await session.execute(update(Poll).where(Poll.id == poll.id).values(message_id=str(message.id)))

    @encuesta.command(name="finalizar", description="Finalizar una encuesta activa")
    @app_commands.describe(id="ID de la encuesta (primeros 8 caracteres)")
    async def poll_end(self, interaction: discord.Interaction, id: str) -> None:
        async with self.bot.db.session() as session:
            poll = (await session.execute(select(Poll).where(
                Poll.id.startswith(id), Poll.guild_id == str(interaction.guild_id), Poll.ended.is_(False)).limit(1)
            )).scalar_one_or_none()
            if poll is None:
                await interaction.response.send_message("Encuesta no encontrada o ya finalizada.", ephemeral=True)
                return
            if poll.creator_id != str(interaction.user.id) and not interaction.permissions.manage_messages:
                await interaction.response.send_message("Solo el creador o moderadores pueden finalizar esta encuesta.",
                                                        ephemeral=True)
                return
            poll.ended = True
        await interaction.response.send_message(embed=poll_embed(poll, ended=True))
        await self._close_poll_message(poll)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Automation(bot))
