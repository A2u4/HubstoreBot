"""Rifas (numbered raffles): staff-managed slots, request channels, timed or manual draws."""

from __future__ import annotations

import asyncio
import io
import logging
import re
from datetime import timedelta
from typing import Any

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import or_, select, update

from markets_bot.bot import MarketsBot
from markets_bot.core.tasks import resilient
from markets_bot.core.utils import ERROR, OK, crypto_sample, discord_ts, utcnow
from markets_bot.db.base import new_id
from markets_bot.db.models import Rifa
from markets_bot.web.internal_server import HttpError, json_response, read_json

log = logging.getLogger(__name__)

RIFA_COLOR = 0xE91E8C
ENDED_COLOR = 0x99AAB5
WIN_COLOR = 0xF1C40F
HISTORY_BLUE = 0x3498DB
DEFAULT_CATEGORY = "1489245171953434805"
_DURATION_RE = re.compile(r"^(\d+)(s|m|h|d)$", re.IGNORECASE)
_ALLOW = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)


def free_slots(participants: list[str]) -> list[int]:
    return [i for i, uid in enumerate(participants) if not uid]


def filled(participants: list[str]) -> int:
    return sum(1 for uid in participants if uid)


def parse_rifa_duration(text: str) -> timedelta | None:
    match = _DURATION_RE.match(text.strip())
    if not match:
        return None
    return timedelta(seconds=int(match.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2).lower()])


def rifa_embed(rifa: Rifa, table: str | None = None) -> discord.Embed:
    count = filled(rifa.participants)
    over = rifa.ended or rifa.cancelled
    title = "🎟️ RIFA" + (" — FINALIZADA" if rifa.ended else " — CANCELADA" if rifa.cancelled else "")
    description = f"**🏆 Premio:** {rifa.prize}"
    if rifa.description:
        description += f"\n> {rifa.description}"
    if table:
        description += f"\n```\n{table}\n```"
    embed = discord.Embed(color=ENDED_COLOR if over else RIFA_COLOR, title=title, description=description[:4096],
                          timestamp=discord.utils.utcnow())
    embed.add_field(name="👥 Participantes", value=f"**{count}** / {rifa.max_slots}", inline=True)
    embed.add_field(name="🎯 Ganadores", value=str(rifa.winners_count), inline=True)
    embed.add_field(name="⏰ Sorteo", value=discord_ts(rifa.ends_at) if rifa.ends_at else "Manual (staff)", inline=True)
    embed.add_field(name="🎪 Organizador", value=f"<@{rifa.host_id}>", inline=True)
    embed.add_field(name="🔢 Slots libres", inline=True,
                    value=" ".join(f"#{i + 1}" for i in free_slots(rifa.participants)[:15]) or "Ninguno")
    embed.add_field(name="🎫 Tickets", value="Abierto para usuarios", inline=True)
    embed.set_footer(text="Rifa finalizada" if rifa.ended else "Rifa cancelada" if rifa.cancelled else
                     "¡Todos los slots llenos!" if count >= rifa.max_slots else
                     "Haz clic en el boton para solicitar tu numero al staff")
    if rifa.ended and rifa.winner_ids:
        embed.color = WIN_COLOR
        embed.add_field(name="🥇 Ganador(es)", value=", ".join(f"<@{w}>" for w in rifa.winner_ids), inline=False)
    return embed


def rifa_view(rifa: Rifa) -> discord.ui.View | None:
    if rifa.ended or rifa.cancelled:
        return None
    count = filled(rifa.participants)
    full = count >= rifa.max_slots
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(custom_id=f"rifa_ticket_{rifa.id}", label="Solicitar mi numero (ticket al staff)",
                                    style=discord.ButtonStyle.success))
    view.add_item(discord.ui.Button(custom_id=f"rifa_slots_{rifa.id}", disabled=True,
                                    label="Slots llenos" if full else f"Participantes: {count}/{rifa.max_slots}",
                                    style=discord.ButtonStyle.danger if full else discord.ButtonStyle.secondary))
    return view


class Rifas(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self._tick = 0
        r = bot.router
        r.prefix("button", "rifa_join_", self.on_join)
        r.prefix("button", "rifa_ticket_", self.on_ticket)
        r.prefix("button", "rifa_panel_ticket_", self.on_panel_ticket)
        bot.internal.route("POST", "/internal/rifas/deploy-panel")(self._deploy_panel_route)
        bot.internal.route("POST", "/internal/rifas/draw")(self._draw_route)
        bot.internal.route("POST", "/internal/rifas/cancel")(self._cancel_route)

    async def cog_load(self) -> None:
        self.timer.start()

    async def cog_unload(self) -> None:
        self.timer.cancel()

    # ── Rendering ────────────────────────────────────────────────────────

    async def table(self, rifa: Rifa) -> str:
        guild = self.bot.get_guild(int(rifa.guild_id))
        lines = ["Puesto │ Usuario", "───────┼────────────────────"]
        for index, uid in enumerate(rifa.participants):
            if not uid:
                name = "(libre)"
            else:
                member = guild.get_member(int(uid)) if guild else None
                name = member.display_name if member else f"ID:{uid[-5:]}"
            lines.append(f"{str(index + 1).rjust(6)} │ {name}")
        return "\n".join(lines)

    async def refresh_message(self, rifa: Rifa) -> None:
        if not rifa.message_id:
            return
        channel = self.bot.get_channel(int(rifa.channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            return
        try:
            message = await channel.fetch_message(int(rifa.message_id))
            await message.edit(embed=rifa_embed(rifa, await self.table(rifa)), view=rifa_view(rifa))
        except discord.HTTPException as exc:
            log.warning("Could not update rifa message %s: %s", rifa.id, exc)

    async def draw(self, rifa_id: str, forced_by: int | str | None = None) -> Rifa | None:
        async with self.bot.db.session() as session:
            rifa = await session.get(Rifa, rifa_id, with_for_update=True)
            if rifa is None or rifa.ended or rifa.cancelled:
                return None
            winners = crypto_sample([p for p in rifa.participants if p], rifa.winners_count)
            rifa.ended = True
            rifa.winner_ids = winners
        await self.refresh_message(rifa)
        channel = self.bot.get_channel(int(rifa.channel_id))
        if isinstance(channel, discord.abc.Messageable):
            try:
                if winners:
                    mention = ", ".join(f"<@{w}>" for w in winners)
                    description = (f"**Premio:** {rifa.prize}\n\n🥇 **Ganador(es):** {mention}\n"
                                   f"🎪 **Organizado por:** <@{rifa.host_id}>")
                    if forced_by:
                        description += f"\n🔧 **Sorteado por:** <@{forced_by}>"
                    await channel.send(content=f"🎉 {mention}", embed=discord.Embed(
                        color=WIN_COLOR, title="🎟️ ¡Tenemos ganador(es)!", description=description,
                        timestamp=discord.utils.utcnow()))
                else:
                    await channel.send(embed=discord.Embed(
                        color=ENDED_COLOR, description=f"La rifa de **{rifa.prize}** finalizó sin participantes.",
                        timestamp=discord.utils.utcnow()))
            except discord.HTTPException:
                log.exception("Error announcing rifa winner %s", rifa_id)
        log.info("Rifa %s ended — winners: %s", rifa_id, winners)
        return rifa

    # ── Request channels ─────────────────────────────────────────────────

    async def on_join(self, interaction: discord.Interaction) -> None:
        # Self-join is disabled: staff assigns numbers with /rifa inscribir.
        await interaction.response.send_message(
            "Para participar en la rifa, usa el boton de ticket y el staff te asignara un numero.", ephemeral=True)

    @staticmethod
    def _existing_request(guild: discord.Guild, user_id: int) -> discord.TextChannel | None:
        return discord.utils.find(lambda c: c.name.startswith("rifa-") and f"userId:{user_id}" in (c.topic or ""),
                                  guild.text_channels)

    async def _open_request(self, interaction: discord.Interaction, category_id: str | None, topic: str,
                            embed: discord.Embed, staff_ping_suffix: str = "") -> None:
        guild = interaction.guild
        assert guild is not None
        config = await self.bot.configs.get(guild.id)
        staff = list(config.rifa_staff_role_ids or []) or list(config.ticket_staff_role_ids or [])
        overwrites: dict[Any, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: _ALLOW}
        for rid in staff:
            role = guild.get_role(int(rid)) if rid.isdigit() else None
            if role is not None:
                overwrites[role] = _ALLOW
        category = guild.get_channel(int(category_id)) if category_id and category_id.isdigit() else None
        name = "rifa-" + re.sub(r"[^a-z0-9]", "", interaction.user.name[:15].lower())
        try:
            channel = await guild.create_text_channel(
                name, topic=topic, overwrites=overwrites,
                category=category if isinstance(category, discord.CategoryChannel) else None)
        except discord.HTTPException:
            log.exception("Could not create rifa request channel")
            await interaction.edit_original_response(content="❌ No pude crear el canal. Verifica mis permisos.")
            return
        ping = " ".join(f"<@&{r}>" for r in staff)
        await channel.send(content=(f"{ping}{staff_ping_suffix}" if ping else staff_ping_suffix.removeprefix(" — ")) or None,
                           embed=embed, allowed_mentions=discord.AllowedMentions(roles=True, users=True))
        await interaction.edit_original_response(content=f"✅ Canal creado: {channel.mention}\nIndica ahí qué número quieres.")
        log.info("Rifa request channel %s created for %s", channel.id, interaction.user.id)

    async def on_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        rifa_id = str((interaction.data or {}).get("custom_id", "")).removeprefix("rifa_ticket_")
        async with self.bot.db.session() as session:
            rifa = await session.get(Rifa, rifa_id)
        if rifa is None or rifa.ended or rifa.cancelled:
            await interaction.response.send_message("Esta rifa ya no está activa.", ephemeral=True)
            return
        existing = self._existing_request(guild, interaction.user.id)
        if existing:
            await interaction.response.send_message(f"Ya tienes un canal de solicitud abierto: {existing.mention}",
                                                    ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        config = await self.bot.configs.get(guild.id)
        parent = getattr(interaction.channel, "category_id", None)
        category_id = config.rifa_category_id or config.ticket_category_id or (str(parent) if parent else None)
        free = "  ".join(f"#{i + 1}" for i in free_slots(rifa.participants)) or "Ninguno"
        user = interaction.user.mention
        embed = discord.Embed(color=RIFA_COLOR, title="🎟️ Solicitud de inscripción en rifa", timestamp=discord.utils.utcnow(),
                              description=f"{user} quiere inscribirse en la rifa.\n\n**🏆 Premio:** {rifa.prize}\n"
                                          f"**👥 Participantes actuales:** {filled(rifa.participants)} / {rifa.max_slots}\n"
                                          f"**🔢 Slots libres:** {free}\n\n{user} — indica qué número quieres (ej: `5`) o "
                                          "escribe `aleatorio` para que te asignemos uno libre.")
        embed.add_field(name="✅ Para el staff", value="Usa `/rifa inscribir @usuario puesto:N` aquí mismo para confirmar "
                                                       "la inscripción.\nO usa `/rifa quitar` si se cancela.")
        embed.set_footer(text="Canal se puede cerrar con /ticket cerrar una vez terminado")
        await self._open_request(interaction, category_id, f"Solicitud rifa | userId:{interaction.user.id} | rifaId:{rifa.id}",
                                 embed, f" — solicitud de inscripción de {user}")

    async def on_panel_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        category_id = str((interaction.data or {}).get("custom_id", "")).rsplit("_", 1)[-1]
        existing = self._existing_request(guild, interaction.user.id)
        if existing:
            await interaction.response.send_message(f"Ya tienes un canal abierto: {existing.mention}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        rifa = await self.active(guild.id)
        if rifa:
            free = ", ".join(str(i + 1) for i in free_slots(rifa.participants)[:20]) or "Ninguno"
            info = (f"Premio: {rifa.prize}\nSlots libres: {free}\n\nEscribe el numero que deseas (ej: 5) o "
                    '"aleatorio".')
        else:
            info = "No hay ninguna rifa activa ahora mismo. El staff te avisara cuando haya una."
        embed = discord.Embed(color=RIFA_COLOR, title="Solicitud de numero de rifa", timestamp=discord.utils.utcnow(),
                              description=f"Hola {interaction.user.mention}!\n\n{info}")
        embed.add_field(name="Para el staff", value="Usa /rifa inscribir @usuario puesto:N para confirmar. Cierra el "
                                                    "canal cuando termines.")
        embed.set_footer(text="Rifas")
        await self._open_request(interaction, None if category_id == "null" else category_id,
                                 f"Solicitud rifa | userId:{interaction.user.id}", embed)

    # ── Timer ────────────────────────────────────────────────────────────

    @tasks.loop(seconds=30)
    @resilient
    async def timer(self) -> None:
        self._tick += 1
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        async with self.bot.db.session() as session:
            expired = (await session.execute(select(Rifa.id).where(
                Rifa.guild_id.in_(guild_ids), Rifa.ended.is_(False), Rifa.cancelled.is_(False),
                Rifa.ends_at <= utcnow()))).scalars().all()
        for rifa_id in expired:
            await self.draw(rifa_id)
        if self._tick % 10 == 0:  # refresh countdown embeds every 5 minutes
            async with self.bot.db.session() as session:
                active = (await session.execute(select(Rifa).where(
                    Rifa.guild_id.in_(guild_ids), Rifa.ended.is_(False), Rifa.cancelled.is_(False),
                    Rifa.ends_at.is_not(None)))).scalars().all()
            for rifa in active:
                await self.refresh_message(rifa)

    @timer.before_loop
    async def _wait(self) -> None:
        await self.bot.wait_until_ready()

    # ── /rifa ────────────────────────────────────────────────────────────

    async def active(self, guild_id: int | str) -> Rifa | None:
        async with self.bot.db.session() as session:
            return (await session.execute(select(Rifa).where(
                Rifa.guild_id == str(guild_id), Rifa.ended.is_(False), Rifa.cancelled.is_(False)
            ).order_by(Rifa.created_at.desc()).limit(1))).scalar_one_or_none()

    @staticmethod
    async def _staff_only(interaction: discord.Interaction, message: str) -> bool:
        perms = interaction.permissions
        if perms.manage_guild or perms.administrator:
            return True
        await interaction.response.send_message(message, ephemeral=True)
        return False

    rifa = app_commands.Group(name="rifa", description="Sistema completo de rifas", guild_only=True,
                              extras={"module": "rifa", "cooldown": 3})

    @rifa.command(name="crear", description="Crear una nueva rifa")
    @app_commands.rename(auto_sortear="auto-sortear", auto_join="auto-join")
    @app_commands.describe(premio="Premio de la rifa", limite="Número máximo de participantes",
                           ganadores="Cantidad de ganadores (def: 1)", duracion="Duración: 30m, 2h, 1d (vacío = manual)",
                           descripcion="Descripción adicional", canal="Canal donde publicar",
                           auto_sortear="Sortear al llenarse los slots (def: no)",
                           auto_join="Usuarios se inscriben solos (def: sí)")
    async def create(self, interaction: discord.Interaction, premio: str, limite: app_commands.Range[int, 2, 500],
                     ganadores: app_commands.Range[int, 1, 20] = 1, duracion: str | None = None,
                     descripcion: str | None = None, canal: discord.TextChannel | None = None,
                     auto_sortear: bool = False, auto_join: bool = True) -> None:
        if not await self._staff_only(interaction, "Solo el staff puede crear rifas."):
            return
        if await self.active(interaction.guild_id or 0):
            await interaction.response.send_message(embed=discord.Embed(
                color=ERROR, description="⚠️ Ya hay una rifa activa. Cancélala o sortéala primero."), ephemeral=True)
            return
        ends_at = None
        if duracion:
            span = parse_rifa_duration(duracion)
            if span is None:
                await interaction.response.send_message("Duración inválida. Ejemplo: `30m`, `2h`, `1d`", ephemeral=True)
                return
            ends_at = utcnow() + span
        target = canal or interaction.channel
        if not isinstance(target, discord.abc.Messageable):
            await interaction.response.send_message("Canal inválido.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        # The ID is needed for the button custom_id before the row is inserted.
        rifa = Rifa(id=new_id(), ended=False, cancelled=False, guild_id=str(interaction.guild_id), channel_id=str(target.id), host_id=str(interaction.user.id),  # type: ignore[union-attr]
                    prize=premio, description=descripcion, max_slots=limite, winners_count=ganadores, ends_at=ends_at,
                    auto_draw_on_full=auto_sortear, allow_self_join=auto_join, participants=[""] * limite)
        message = await target.send(embed=rifa_embed(rifa, await self.table(rifa)), view=rifa_view(rifa))
        rifa.message_id = str(message.id)
        async with self.bot.db.session() as session:
            session.add(rifa)
        embed = discord.Embed(color=OK, title="✅ Rifa creada")
        for name, value in (("🏆 Premio", premio), ("👥 Slots", str(limite)), ("🎯 Ganadores", str(ganadores)),
                            ("⏰ Duración", discord_ts(ends_at) if ends_at else "Manual"),
                            ("🔄 Auto-sortear", "Sí" if auto_sortear else "No"), ("🎫 Auto-join", "Sí" if auto_join else "No"),
                            ("📢 Canal", f"<#{target.id}>")):  # type: ignore[union-attr]
            embed.add_field(name=name, value=value, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @rifa.command(name="inscribir", description="Inscribir a un usuario (staff)")
    @app_commands.describe(usuario="Usuario a inscribir", puesto="Número de puesto específico (vacío = primer libre)")
    async def enroll(self, interaction: discord.Interaction, usuario: discord.User,
                     puesto: app_commands.Range[int, 1] | None = None) -> None:
        if not await self._staff_only(interaction, "Solo el staff puede inscribir usuarios."):
            return
        async with self.bot.db.session() as session:
            rifa = (await session.execute(select(Rifa).where(
                Rifa.guild_id == str(interaction.guild_id), Rifa.ended.is_(False), Rifa.cancelled.is_(False)
            ).order_by(Rifa.created_at.desc()).limit(1).with_for_update())).scalar_one_or_none()
            if rifa is None:
                await interaction.response.send_message("No hay ninguna rifa activa.", ephemeral=True)
                return
            parts = list(rifa.participants)
            if str(usuario.id) in parts:
                await interaction.response.send_message(f"{usuario.mention} ya está inscrito en la rifa.", ephemeral=True)
                return
            if puesto is not None:
                index = puesto - 1
                if index >= rifa.max_slots:
                    await interaction.response.send_message(f"❌ El puesto debe estar entre 1 y {rifa.max_slots}.",
                                                            ephemeral=True)
                    return
                if parts[index]:
                    await interaction.response.send_message(
                        f"❌ El puesto **#{puesto}** ya está ocupado por <@{parts[index]}>.", ephemeral=True)
                    return
            else:
                index = next((i for i, uid in enumerate(parts) if not uid), -1)
                if index < 0:
                    await interaction.response.send_message("¡Los slots están llenos!", ephemeral=True)
                    return
            parts[index] = str(usuario.id)
            rifa.participants = parts
        await self.refresh_message(rifa)
        await interaction.response.send_message(embed=discord.Embed(color=OK, description=(
            f"✅ {usuario.mention} inscrito en el puesto **#{index + 1}** de la rifa **{rifa.prize}**.")), ephemeral=True)
        if rifa.auto_draw_on_full and filled(parts) >= rifa.max_slots:
            await asyncio.sleep(3)
            await self.draw(rifa.id, interaction.user.id)

    @rifa.command(name="quitar", description="Quitar a un usuario de la rifa (staff)")
    @app_commands.describe(usuario="Usuario a quitar")
    async def remove(self, interaction: discord.Interaction, usuario: discord.User) -> None:
        if not await self._staff_only(interaction, "Solo el staff puede quitar usuarios."):
            return
        async with self.bot.db.session() as session:
            rifa = (await session.execute(select(Rifa).where(
                Rifa.guild_id == str(interaction.guild_id), Rifa.ended.is_(False), Rifa.cancelled.is_(False)
            ).order_by(Rifa.created_at.desc()).limit(1).with_for_update())).scalar_one_or_none()
            if rifa is None:
                await interaction.response.send_message("No hay ninguna rifa activa.", ephemeral=True)
                return
            parts = list(rifa.participants)
            if str(usuario.id) not in parts:
                await interaction.response.send_message(f"{usuario.mention} no está inscrito en la rifa.", ephemeral=True)
                return
            index = parts.index(str(usuario.id))
            parts[index] = ""
            rifa.participants = parts
        await self.refresh_message(rifa)
        await interaction.response.send_message(embed=discord.Embed(color=OK, description=(
            f"✅ {usuario.mention} quitado del puesto **#{index + 1}**. El slot queda libre.")), ephemeral=True)

    @rifa.command(name="listar", description="Ver la tabla de participantes de la rifa activa")
    async def list_(self, interaction: discord.Interaction) -> None:
        rifa = await self.active(interaction.guild_id or 0)
        if rifa is None:
            async with self.bot.db.session() as session:
                rifa = (await session.execute(select(Rifa).where(Rifa.guild_id == str(interaction.guild_id))
                                              .order_by(Rifa.created_at.desc()).limit(1))).scalar_one_or_none()
        if rifa is None:
            await interaction.response.send_message("No hay ninguna rifa en curso.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        table = await self.table(rifa)
        footer = [f"👥 Total: {filled(rifa.participants)} / {rifa.max_slots} participantes"]
        if rifa.ends_at:
            footer.append(f"⏰ Sorteo: {discord_ts(rifa.ends_at)}")
        text = "\n".join([f"🎟️  Rifa: {rifa.prize}", "", table, "", *footer])
        if len(text) > 1800:
            await interaction.followup.send(f"📋 Lista completa de participantes ({rifa.prize}):",
                                            file=discord.File(io.BytesIO(text.encode()), "participantes.txt"), ephemeral=True)
            return
        embed = discord.Embed(color=RIFA_COLOR, title=f"🎟️ Rifa actual: {rifa.prize}",
                              description=f"```\n{table}\n\n{chr(10).join(footer)}\n```")
        embed.set_footer(text=f"{filled(rifa.participants)} / {rifa.max_slots} participantes")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @rifa.command(name="info", description="Resumen de la rifa activa")
    async def info(self, interaction: discord.Interaction) -> None:
        rifa = await self.active(interaction.guild_id or 0)
        if rifa is None:
            await interaction.response.send_message("No hay ninguna rifa activa.", ephemeral=True)
            return
        free = free_slots(rifa.participants)
        embed = discord.Embed(color=RIFA_COLOR, title="🎟️ Rifa activa — Información", timestamp=discord.utils.utcnow())
        embed.add_field(name="🏆 Premio", value=rifa.prize, inline=False)
        embed.add_field(name="👥 Participantes", value=f"{filled(rifa.participants)} / {rifa.max_slots}", inline=True)
        embed.add_field(name="🎯 Ganadores", value=str(rifa.winners_count), inline=True)
        embed.add_field(name="🔢 Slots libres", value=f"{len(free)} ({' '.join(f'#{i + 1}' for i in free[:10])})", inline=False)
        embed.add_field(name="⏰ Sorteo", value=discord_ts(rifa.ends_at) if rifa.ends_at else "Manual", inline=True)
        embed.add_field(name="🎪 Organizador", value=f"<@{rifa.host_id}>", inline=True)
        embed.add_field(name="🔄 Auto-sortear", value="Al llenarse" if rifa.auto_draw_on_full else "No", inline=True)
        embed.add_field(name="🎫 Auto-join", value="Sí" if rifa.allow_self_join else "No", inline=True)
        embed.add_field(name="📢 Canal", value=f"<#{rifa.channel_id}>", inline=True)
        embed.add_field(name="📅 Creada", value=discord_ts(rifa.created_at, "f"), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @rifa.command(name="sortear", description="Realizar el sorteo manualmente (staff)")
    async def draw_cmd(self, interaction: discord.Interaction) -> None:
        if not await self._staff_only(interaction, "Solo el staff puede sortear."):
            return
        rifa = await self.active(interaction.guild_id or 0)
        if rifa is None:
            await interaction.response.send_message("No hay ninguna rifa activa.", ephemeral=True)
            return
        if filled(rifa.participants) == 0:
            await interaction.response.send_message("No hay participantes en la rifa.", ephemeral=True)
            return
        await interaction.response.send_message(embed=discord.Embed(color=RIFA_COLOR, description="🎰 Realizando el sorteo..."),
                                                ephemeral=True)
        await self.draw(rifa.id, interaction.user.id)

    @rifa.command(name="reroll", description="Repetir el sorteo de la última rifa (staff)")
    async def reroll(self, interaction: discord.Interaction) -> None:
        if not await self._staff_only(interaction, "Solo el staff puede hacer reroll."):
            return
        async with self.bot.db.session() as session:
            last = (await session.execute(select(Rifa).where(
                Rifa.guild_id == str(interaction.guild_id), Rifa.ended.is_(True), Rifa.cancelled.is_(False)
            ).order_by(Rifa.updated_at.desc()).limit(1))).scalar_one_or_none()
            if last is None:
                await interaction.response.send_message("No hay ninguna rifa finalizada.", ephemeral=True)
                return
            winners = crypto_sample([p for p in last.participants if p], last.winners_count)
            await session.execute(update(Rifa).where(Rifa.id == last.id).values(winner_ids=winners))
        mention = ", ".join(f"<@{w}>" for w in winners)
        channel = self.bot.get_channel(int(last.channel_id))
        if winners and isinstance(channel, discord.abc.Messageable):
            await channel.send(content=f"🔄 {mention}", embed=discord.Embed(
                color=WIN_COLOR, title="🔄 Reroll — Nuevos ganadores", timestamp=discord.utils.utcnow(),
                description=f"**Premio:** {last.prize}\n\n🥇 **Ganador(es):** {mention}\n🔧 **Reroll por:** "
                            f"{interaction.user.mention}"))
        await interaction.response.send_message(embed=discord.Embed(color=OK, description=(
            f"✅ Reroll de **{last.prize}**\n🥇 Nuevos ganadores: {mention or 'Ninguno'}")), ephemeral=True)

    @rifa.command(name="cancelar", description="Cancelar la rifa activa (staff)")
    @app_commands.describe(motivo="Motivo de la cancelación")
    async def cancel(self, interaction: discord.Interaction, motivo: str = "Sin motivo") -> None:
        if not await self._staff_only(interaction, "Solo el staff puede cancelar rifas."):
            return
        rifa = await self.active(interaction.guild_id or 0)
        if rifa is None:
            await interaction.response.send_message("No hay ninguna rifa activa.", ephemeral=True)
            return
        await self._cancel(rifa, motivo, interaction.user.id)
        await interaction.response.send_message(embed=discord.Embed(
            color=OK, description=f"✅ Rifa **{rifa.prize}** cancelada."), ephemeral=True)

    async def _cancel(self, rifa: Rifa, reason: str, by: int | str | None) -> None:
        async with self.bot.db.session() as session:
            await session.execute(update(Rifa).where(Rifa.id == rifa.id).values(cancelled=True))
        rifa.cancelled = True
        await self.refresh_message(rifa)
        channel = self.bot.get_channel(int(rifa.channel_id))
        if isinstance(channel, discord.abc.Messageable):
            try:
                await channel.send(embed=discord.Embed(
                    color=ERROR, title="❌ Rifa cancelada", timestamp=discord.utils.utcnow(),
                    description=f"**Premio:** {rifa.prize}\n**Motivo:** {reason}\n**Cancelada por:** "
                                f"{f'<@{by}>' if by and str(by).isdigit() else 'Dashboard'}"))
            except discord.HTTPException:
                pass

    @rifa.command(name="historial", description="Ver las últimas rifas realizadas")
    async def history(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(Rifa).where(
                Rifa.guild_id == str(interaction.guild_id), or_(Rifa.ended.is_(True), Rifa.cancelled.is_(True))
            ).order_by(Rifa.updated_at.desc()).limit(5))).scalars().all()
        if not rows:
            await interaction.response.send_message("No hay rifas en el historial.", ephemeral=True)
            return
        embed = discord.Embed(color=HISTORY_BLUE, title="📋 Historial de rifas (últimas 5)", timestamp=discord.utils.utcnow())
        for r in rows:
            winners = ", ".join(f"<@{w}>" for w in r.winner_ids or []) or "Ninguno"
            value = f"👥 {filled(r.participants)}/{r.max_slots} participantes"
            if r.ended:
                value += f"\n🥇 {winners}"
            value += f"\n📅 {discord_ts(r.updated_at, 'f')}"
            embed.add_field(name=f"{'❌ Cancelada' if r.cancelled else '✅ Finalizada'} — {r.prize}", value=value, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Dashboard actions ────────────────────────────────────────────────

    async def _deploy_panel_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        guild_id, channel_id = str(body.get("guildId")), str(body.get("channelId") or "")
        if not channel_id:
            raise HttpError(400, "channelId es requerido")
        config = await self.bot.configs.get(guild_id)
        channel = self.bot.get_channel(int(channel_id)) if channel_id.isdigit() else None
        if not isinstance(channel, discord.TextChannel) or str(channel.guild.id) != guild_id:
            raise HttpError(404, "Canal no encontrado")
        category_id = config.rifa_category_id or DEFAULT_CATEGORY
        embed = discord.Embed(color=RIFA_COLOR, title=body.get("title") or "🎟️ Rifas — Soporte",
                              description=body.get("description") or "Haz clic en el botón para solicitar tu número de "
                                                                     "rifa.\nEl staff te atenderá en un canal privado.",
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text="Sistema de Rifas")
        try:
            style = discord.ButtonStyle(int(body.get("buttonColor") or 3))
        except ValueError:
            style = discord.ButtonStyle.success
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(custom_id=f"rifa_panel_ticket_{guild_id}_{category_id}", style=style,
                                        label=body.get("buttonLabel") or "🎫 Solicitar número de rifa"))
        if config.rifa_panel_channel_id and config.rifa_panel_message_id:
            old = self.bot.get_channel(int(config.rifa_panel_channel_id))
            if isinstance(old, discord.abc.Messageable):
                try:
                    await old.get_partial_message(int(config.rifa_panel_message_id)).delete()  # type: ignore[attr-defined]
                except discord.HTTPException:
                    pass
        try:
            message = await channel.send(embed=embed, view=view)
        except discord.HTTPException as exc:
            raise HttpError(400, f"Error al enviar el panel a Discord: {exc}") from exc
        await self.bot.configs.update(guild_id, rifa_panel_channel_id=channel_id, rifa_panel_message_id=str(message.id))
        return json_response({"success": True, "messageId": str(message.id), "channelId": channel_id})

    async def _draw_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        async with self.bot.db.session() as session:
            rifa = await session.get(Rifa, str(body.get("rifaId")))
        if rifa is None or rifa.guild_id != str(body.get("guildId")):
            raise HttpError(404, "Rifa no encontrada")
        if rifa.ended or rifa.cancelled:
            raise HttpError(400, "La rifa ya finalizó o fue cancelada")
        updated = await self.draw(rifa.id, body.get("by"))
        return json_response({"success": True, "winnerIds": updated.winner_ids if updated else []})

    async def _cancel_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        async with self.bot.db.session() as session:
            rifa = await session.get(Rifa, str(body.get("rifaId")))
        if rifa is None or rifa.guild_id != str(body.get("guildId")):
            raise HttpError(404, "Rifa no encontrada")
        await self._cancel(rifa, str(body.get("reason") or "Cancelada desde el dashboard"), body.get("by"))
        return json_response({"success": True})


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Rifas(bot))
