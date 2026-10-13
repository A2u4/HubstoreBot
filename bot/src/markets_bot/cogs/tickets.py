"""Ticket system: panels, buttons, forms, claiming, transcripts, auto-close and cleanup."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import timedelta

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import delete, func, select, update

from markets_bot.bot import MarketsBot
from markets_bot.core.audit import text_channel
from markets_bot.core.cache import TtlCache
from markets_bot.core.pipeline import MessagePipeline
from markets_bot.core.router import modal_values, select_values
from markets_bot.core.tasks import resilient
from markets_bot.core.utils import ERROR, INFO, OK, WARN, discord_ts, format_duration, is_snowflake, utcnow
from markets_bot.db.models import GuildConfig, Ticket, TicketPanel, TicketTranscript
from markets_bot.services.tickets.manager import CreateOptions, TicketService
from markets_bot.services.tickets.ui import (
    CREATE_PREFIX,
    PRIORITY_COLORS,
    PRIORITY_EMOJI,
    close_confirmation,
    closed_actions,
    form_modal,
    order_panels,
    pad,
    panel_message,
    panel_order_from_components,
    parse_emoji,
    ticket_actions,
)
from markets_bot.web.internal_server import HttpError, json_response, read_json

log = logging.getLogger(__name__)

AUTO_CLOSE_BATCH = 5
CLEANUP_BATCH = 5
CLOSED_RETENTION = timedelta(days=7)
PROTECTED_TICKET_RE = re.compile(r"turr", re.IGNORECASE)
ACTIVITY_WRITE_INTERVAL = 60
PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
PRIORITY_CHOICES = [app_commands.Choice(name=n, value=v) for n, v in
                    (("Baja", "low"), ("Normal", "normal"), ("Alta", "high"), ("Urgente", "urgent"))]

INACTIVITY_NOTICE = ("\n\n⏱️ **Inactividad**\nEste ticket se cerrará automáticamente después de 24 horas sin "
                     "actividad. Un miembro del staff puede desactivar el cierre automático si es necesario.")
PRESET_TYPES = [
    ("mediacion", "Mediación", "🤝", "Primary", "categoria_mediacion",
     "🤝 **Solicitud de mediación**\nUn miembro del staff te atenderá en breve. Mientras esperas, indica qué se "
     "intercambiará, el valor total de la operación y quién es el otro usuario.\n\nUsa `/tarifa-mediacion` para "
     "consultar las tarifas y formas de pago." + INACTIVITY_NOTICE),
    ("soporte", "Soporte", "🔧", "Secondary", "categoria_soporte",
     "🔧 **Solicitud de soporte**\nUn miembro del staff te atenderá en breve. Describe tu duda, problema o "
     "inconveniente con el mayor detalle posible y adjunta capturas si pueden ayudarnos a resolverlo." + INACTIVITY_NOTICE),
    ("verificacion-ooc", "Rangos", "⭐", "Success", "categoria_verificacion",
     "⭐ **Solicitud de rango**\nUn miembro del staff te atenderá en breve. Indica si deseas solicitar Shopper, Access "
     "o VIP y sigue las instrucciones de verificación del staff.\n\nUsa `/rango` para consultar requisitos, "
     "beneficios, precios y el proceso para recibir tu rol." + INACTIVITY_NOTICE),
    ("estafas", "Estafas", "🚨", "Danger", "categoria_estafas",
     "🚨 **Reporte de estafa**\nUn miembro del staff revisará tu caso en breve. Explica lo ocurrido, menciona al "
     "usuario involucrado y adjunta capturas, comprobantes o cualquier otra evidencia disponible. Evita borrar "
     "mensajes relacionados con el caso." + INACTIVITY_NOTICE),
]
PRESET_DESCRIPTION = (
    "🤝 **Mediación** – Intermediación segura para tus compras y ventas. Consulta `/tarifa-mediacion` para ver "
    "precios y formas de pago.\n\n🔧 **Soporte** – Ayuda con dudas, problemas o inconvenientes del marketplace.\n\n"
    "⭐ **Rangos** – Solicita Shopper, Access o VIP. Consulta `/rango` para ver requisitos, precios y el proceso para "
    "recibir tu rol.\n\n🚨 **Estafas** – Reporta intentos de estafa o casos consumados y adjunta todas las pruebas "
    "disponibles.\n\n⏱️ **Inactividad** – Los tickets se cierran automáticamente después de 24 horas sin actividad, "
    "salvo que el staff desactive el cierre automático."
)


async def _ephemeral(interaction: discord.Interaction, content: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


class Tickets(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self.service = TicketService(bot)
        # channel id -> (ticket id, creator id, first response recorded) | None for non-ticket channels
        self._ticket_channels: TtlCache[tuple[str, str, bool] | bool] = TtlCache(120, 20_000)
        self._last_activity_write: TtlCache[float] = TtlCache(ACTIVITY_WRITE_INTERVAL, 20_000)
        self._repost_channels: TtlCache[set[str]] = TtlCache(60, 1_000)
        self._reposting: set[int] = set()
        self._repost_cooldown: dict[int, float] = {}
        self._rotation_index: dict[str, int] = {}
        self._rotation_last: dict[str, float] = {}
        self._protected_ticket_ids: set[str] = set()

        r = bot.router
        r.prefix("button", CREATE_PREFIX, self.on_create_button)
        r.exact("button", "ticket_close", self.on_close_button)
        r.prefix("button", "ticket_confirm_close_", self.on_confirm_close)
        r.exact("button", "ticket_cancel_close", self.on_cancel_close)
        r.exact("button", "ticket_reopen", self.on_reopen)
        r.exact("button", "ticket_autoclose_toggle", self.on_autoclose_toggle)
        r.exact("button", "ticket_delete", self.service.delete)
        r.exact("button", "ticket_claim", self.on_claim)
        r.exact("button", "ticket_transcript", self.on_transcript)
        r.prefix("button", "ticket_feedback_", self.on_feedback)
        r.exact("select", "ticket_panel_select", self.on_panel_select)
        r.prefix("modal", "ticket_form_", self.on_form_submit)

        bot.pipeline.register("ticket_activity", self.track_activity, MessagePipeline.TICKET_ACTIVITY)
        bot.pipeline.register("panel_repost", self.repost_panel, MessagePipeline.PANEL_REPOST, include_bots=True)

        route = bot.internal.route
        route("POST", "/internal/tickets/deploy")(self._deploy_route)
        route("POST", "/internal/tickets/sync")(self._sync_route)
        route("POST", "/internal/tickets/cross-deploy")(self._cross_deploy_route)
        route("POST", "/internal/tickets/close")(self._close_route)

    async def cog_load(self) -> None:
        self.auto_close.start()
        self.cleanup_closed.start()
        self.rotate_images.start()

    async def cog_unload(self) -> None:
        self.auto_close.cancel()
        self.cleanup_closed.cancel()
        self.rotate_images.cancel()

    # ── Creation ─────────────────────────────────────────────────────────

    async def _start(self, interaction: discord.Interaction, panel_id: str, *, select_limit_message: bool = False) -> None:
        panel = await self.service.panel(panel_id)
        if panel is None:
            await _ephemeral(interaction, "Este panel de tickets ya no existe.")
            return
        if panel.form_enabled and panel.form_questions:
            modal = form_modal(f"ticket_form_{panel.id}", panel.form_title, list(panel.form_questions))
            if modal is not None:
                await interaction.response.send_modal(modal)
                return
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        existing = await self.service.open_tickets(interaction.guild.id, interaction.user.id, panel.id)
        limit = panel.ticket_limit or 1
        if len(existing) >= limit:
            text = ("Ya tienes el máximo de tickets abiertos para esta categoría." if select_limit_message else
                    f"Ya tienes {len(existing)} ticket(s) abierto(s) (límite: {limit}). Ve a <#{existing[0].channel_id}>")
            await interaction.edit_original_response(content=text)
            return
        await self.service.create(interaction, panel)

    async def on_create_button(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        custom_id = str((interaction.data or {}).get("custom_id", ""))
        log.info("Ticket button %s by %s in %s", custom_id, interaction.user.id, interaction.guild.id)
        await self._start(interaction, custom_id.removeprefix(CREATE_PREFIX))

    async def on_panel_select(self, interaction: discord.Interaction) -> None:
        values = select_values(interaction)
        if interaction.guild is None or not values:
            return
        await self._start(interaction, values[0], select_limit_message=True)

    async def on_form_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        panel_id = str((interaction.data or {}).get("custom_id", "")).removeprefix("ticket_form_")
        await interaction.response.defer(ephemeral=True, thinking=True)
        panel = await self.service.panel(panel_id)
        if panel is None:
            await interaction.edit_original_response(content="El panel ya no existe.")
            return
        values = modal_values(interaction)
        questions = list(panel.form_questions or [])[:5]
        answers = [{"question": str(q.get("label", "")), "answer": values.get(f"question_{i}", "").strip()}
                   for i, q in enumerate(questions)]
        await self.service.create(interaction, panel, answers)

    # ── Buttons inside tickets ───────────────────────────────────────────

    async def _context(self, interaction: discord.Interaction) -> tuple[Ticket, TicketPanel | None] | None:
        if interaction.guild is None or interaction.channel_id is None:
            return None
        return await self.service.by_channel(interaction.channel_id)

    async def on_close_button(self, interaction: discord.Interaction) -> None:
        found = await self._context(interaction)
        if found is None or found[0].status != "open":
            await _ephemeral(interaction, "Este no es un ticket abierto.")
            return
        ticket, panel = found
        assert isinstance(interaction.user, discord.Member)
        if not await self.service.can_close(interaction.user, ticket, panel):
            await _ephemeral(interaction, "Solo puede cerrar este ticket la persona que lo abrió o el staff.")
            return
        if panel is None or panel.close_request_enabled:
            embed = discord.Embed(color=WARN, title="¿Cerrar ticket?",
                                  description=(panel.close_request_message if panel else None)
                                  or "¿Estás seguro de que quieres cerrar este ticket?", timestamp=discord.utils.utcnow())
            embed.set_footer(text=f"Solicitado por {interaction.user.name}")
            await interaction.response.send_message(embed=embed, view=close_confirmation(interaction.user.id))
            return
        await interaction.response.defer()
        await self._close_here(interaction, ticket, panel, None)

    async def _close_here(self, interaction: discord.Interaction, ticket: Ticket, panel: TicketPanel | None,
                          reason: str | None) -> discord.Embed:
        channel = interaction.channel
        assert isinstance(channel, discord.TextChannel)
        embed = await self.service.close(channel, ticket, panel, str(interaction.user.id), reason)
        self._ticket_channels.delete(str(channel.id))
        await channel.send(embed=embed, view=closed_actions())
        return embed

    async def on_confirm_close(self, interaction: discord.Interaction) -> None:
        found = await self._context(interaction)
        if found is None or found[0].status != "open":
            await _ephemeral(interaction, "Este ticket ya está cerrado.")
            return
        ticket, panel = found
        requester = str((interaction.data or {}).get("custom_id", "")).rsplit("_", 1)[-1]
        if is_snowflake(requester) and requester != str(interaction.user.id):
            await _ephemeral(interaction, "Solo quien pidió el cierre puede confirmar este botón.")
            return
        assert isinstance(interaction.user, discord.Member)
        if not await self.service.can_close(interaction.user, ticket, panel):
            await _ephemeral(interaction, "Solo puede cerrar este ticket la persona que lo abrió o el staff.")
            return
        await interaction.response.defer()
        try:
            if interaction.message:
                await interaction.message.delete()
        except discord.HTTPException:
            pass
        await self._close_here(interaction, ticket, panel, None)

    async def on_cancel_close(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer()
            if interaction.message:
                await interaction.message.delete()
        except discord.HTTPException:
            pass

    async def _reopen_allowed(self, interaction: discord.Interaction, ticket: Ticket, panel: TicketPanel | None) -> bool:
        auto_closed = ticket.closed_by == "auto-close"
        creator_can = auto_closed and str(interaction.user.id) == ticket.user_id
        assert isinstance(interaction.user, discord.Member)
        if creator_can or await self.service.is_staff(interaction.user, panel):
            return True
        await _ephemeral(interaction, "Solo la persona que abrió el ticket o el staff puede reabrirlo." if auto_closed
                         else "Solo el staff puede reabrir un ticket cerrado manualmente.")
        return False

    async def on_reopen(self, interaction: discord.Interaction) -> None:
        found = await self._context(interaction)
        if found is None or found[0].status != "closed":
            await _ephemeral(interaction, "Este ticket no está cerrado.")
            return
        ticket, panel = found
        if not await self._reopen_allowed(interaction, ticket, panel):
            return
        assert isinstance(interaction.channel, discord.TextChannel)
        await interaction.response.defer()
        embed = await self.service.reopen(interaction.channel, ticket, panel, interaction.user)
        self._ticket_channels.delete(str(interaction.channel.id))
        await interaction.followup.send(embed=embed, view=ticket_actions(panel, ticket))

    async def on_autoclose_toggle(self, interaction: discord.Interaction) -> None:
        found = await self._context(interaction)
        if found is None or found[0].status != "open":
            await _ephemeral(interaction, "Este no es un ticket abierto.")
            return
        ticket, panel = found
        assert isinstance(interaction.user, discord.Member)
        if not await self.service.is_staff(interaction.user, panel):
            await _ephemeral(interaction, "Solo el staff puede cambiar el cierre automático de este ticket.")
            return
        ticket.auto_close_disabled = not ticket.auto_close_disabled
        await self.service.update(ticket.id, auto_close_disabled=ticket.auto_close_disabled)
        await interaction.response.edit_message(view=ticket_actions(panel, ticket))
        hours = (panel.auto_close_hours if panel else None) or 24
        await interaction.followup.send(
            "El cierre automático fue desactivado para este ticket." if ticket.auto_close_disabled else
            f"El cierre automático fue activado. El ticket se cerrará tras {hours} horas de inactividad.", ephemeral=True)

    async def on_claim(self, interaction: discord.Interaction) -> None:
        found = await self._context(interaction)
        if found is None or found[0].status != "open":
            await _ephemeral(interaction, "Este no es un ticket abierto.")
            return
        ticket, panel = found
        if panel is None or not panel.claim_enabled:
            await _ephemeral(interaction, "Reclamar no está habilitado para este panel.")
            return
        await self._claim(interaction, ticket, panel, "Este ticket ya fue reclamado por <@{}>.",
                          "Solo el staff puede reclamar tickets.", "🙋 Este ticket fue reclamado por {}.")

    async def _claim(self, interaction: discord.Interaction, ticket: Ticket, panel: TicketPanel | None,
                     taken: str, not_staff: str, done: str) -> None:
        if ticket.claimed_by:
            await _ephemeral(interaction, taken.format(ticket.claimed_by))
            return
        member = interaction.user
        assert isinstance(member, discord.Member) and isinstance(interaction.channel, discord.TextChannel)
        staff = set(await self.service.staff_roles(member.guild.id, panel)) | set(panel.admin_role_ids or [] if panel else [])
        if not ({str(r.id) for r in member.roles} & staff or member.guild_permissions.manage_guild):
            await _ephemeral(interaction, not_staff)
            return
        await interaction.response.send_message(embed=discord.Embed(
            color=0x3498DB, description=done.format(member.mention), timestamp=discord.utils.utcnow()))
        await self.service.claim(interaction.channel, ticket, panel, member)

    async def on_transcript(self, interaction: discord.Interaction) -> None:
        found = await self._context(interaction)
        if found is None:
            await _ephemeral(interaction, "Este no es un canal de ticket.")
            return
        ticket, panel = found
        channel = interaction.channel
        assert isinstance(channel, discord.TextChannel) and interaction.guild is not None
        await interaction.response.defer(ephemeral=True, thinking=True)
        html, count, _ = await self.service.transcript(channel, ticket, str(interaction.user.id))
        await interaction.followup.send(
            f"Transcripción generada: **{count} mensajes**. Abre el archivo HTML en un navegador para verla.",
            file=self.service.transcript_file(html, ticket.number), ephemeral=True)
        embed = discord.Embed(color=INFO, title=f"📋 Transcripción — Ticket #{pad(ticket.number)}",
                              timestamp=discord.utils.utcnow())
        embed.add_field(name="Canal", value=channel.mention, inline=True)
        embed.add_field(name="Solicitado por", value=interaction.user.mention, inline=True)
        embed.add_field(name="Mensajes", value=str(count), inline=True)
        await self.service.log(interaction.guild, panel, embed, self.service.transcript_file(html, ticket.number))

    async def on_feedback(self, interaction: discord.Interaction) -> None:
        parts = str((interaction.data or {}).get("custom_id", "")).split("_")
        ticket_id = parts[2] if len(parts) > 3 else ""
        rating = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        if not ticket_id or not 1 <= rating <= 5:
            await _ephemeral(interaction, "Valoración inválida.")
            return
        await self.service.update(ticket_id, rating=rating)
        view = discord.ui.View()
        for row in interaction.message.components if interaction.message else []:
            for child in getattr(row, "children", []):
                view.add_item(discord.ui.Button(label=child.label, style=child.style, disabled=True,
                                                custom_id=child.custom_id))
        await interaction.response.edit_message(view=view)
        await interaction.followup.send(
            f"¡Gracias por tu valoración! Calificaste este ticket con **{'⭐' * rating}** ({rating}/5).")

    # ── Message pipeline ─────────────────────────────────────────────────

    async def _ticket_info(self, channel_id: int) -> tuple[str, str, bool] | None:
        key = str(channel_id)
        cached = self._ticket_channels.get(key)
        if cached is not None:
            return cached if isinstance(cached, tuple) else None
        async with self.bot.db.session() as session:
            row = (await session.execute(select(Ticket.id, Ticket.user_id, Ticket.first_response).where(
                Ticket.channel_id == key, Ticket.status == "open"))).first()
        info = (row[0], row[1], row[2] is not None) if row else None
        self._ticket_channels.set(key, info if info else False)
        return info

    async def track_activity(self, message: discord.Message, config: GuildConfig) -> None:
        """Keep ``lastActivityAt`` fresh (for auto-close) and record the first staff response."""
        info = await self._ticket_info(message.channel.id)
        if info is None:
            return
        ticket_id, creator_id, has_first_response = info
        now = time.monotonic()
        key = str(message.channel.id)
        if self._last_activity_write.get(key) is None:
            self._last_activity_write.set(key, now)
            await self.service.update(ticket_id, last_activity_at=utcnow())
        if (not has_first_response and str(message.author.id) != creator_id
                and isinstance(message.author, discord.Member)):
            panel = None
            found = await self.service.by_channel(message.channel.id)
            if found:
                panel = found[1]
            if await self.service.is_staff(message.author, panel):
                async with self.bot.db.session() as session:
                    await session.execute(update(Ticket).where(
                        Ticket.id == ticket_id, Ticket.first_response.is_(None)).values(first_response=utcnow()))
                self._ticket_channels.set(key, (ticket_id, creator_id, True))

    async def _repost_channel_ids(self, guild_id: int) -> set[str]:
        key = str(guild_id)
        cached = self._repost_channels.get(key)
        if cached is not None:
            return cached
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(TicketPanel.channel_id).where(
                TicketPanel.guild_id == key, TicketPanel.panel_auto_repost.is_(True),
                TicketPanel.message_id.is_not(None)).distinct())).scalars().all()
        result = set(rows)
        self._repost_channels.set(key, result)
        return result

    async def repost_panel(self, message: discord.Message, config: GuildConfig) -> None:
        """Sticky ticket panels: keep the panel as the last message of its channel."""
        guild = message.guild
        channel = message.channel
        if guild is None or channel.id in self._reposting or message.author.id == guild.me.id:
            return
        if str(channel.id) not in await self._repost_channel_ids(guild.id):
            return
        async with self.bot.db.session() as session:
            trigger = (await session.execute(select(TicketPanel).where(
                TicketPanel.channel_id == str(channel.id), TicketPanel.guild_id == str(guild.id),
                TicketPanel.panel_auto_repost.is_(True), TicketPanel.message_id.is_not(None)).limit(1)
            )).scalar_one_or_none()
        if trigger is None or trigger.message_id is None:
            return
        if message.author.bot and trigger.panel_auto_repost_ignore_bots:
            return
        cooldown = trigger.panel_auto_repost_cooldown if trigger.panel_auto_repost_cooldown is not None else 5
        if time.monotonic() - self._repost_cooldown.get(channel.id, 0) < cooldown:
            return
        self._reposting.add(channel.id)
        self._repost_cooldown[channel.id] = time.monotonic()
        try:
            async with self.bot.db.session() as session:
                group = list((await session.execute(select(TicketPanel).where(
                    TicketPanel.channel_id == str(channel.id), TicketPanel.guild_id == str(guild.id),
                    TicketPanel.message_id == trigger.message_id).order_by(TicketPanel.created_at))).scalars().all())
            if not group:
                return
            try:
                old = await channel.fetch_message(int(trigger.message_id))
                group = order_panels(group, panel_order_from_components(old.components))
                await old.delete()
            except discord.HTTPException:
                pass
            embed, view = panel_message(group)
            new = await channel.send(embed=embed, view=view)
            async with self.bot.db.session() as session:
                await session.execute(update(TicketPanel).where(
                    TicketPanel.id.in_([p.id for p in group])).values(message_id=str(new.id)))
            log.info("Re-posted %d-button ticket panel in %s", len(group), channel.id)
        finally:
            self._reposting.discard(channel.id)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """A ticket channel deleted by hand must not stay "open" (ghost rows clog auto-close)."""
        async with self.bot.db.session() as session:
            await session.execute(update(Ticket).where(
                Ticket.channel_id == str(channel.id), Ticket.status.in_(("open", "closed"))).values(status="deleted"))
        self._ticket_channels.delete(str(channel.id))

    # ── Background jobs ──────────────────────────────────────────────────

    @tasks.loop(minutes=15)
    @resilient
    async def auto_close(self) -> None:
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        async with self.bot.db.session() as session:
            rows = (await session.execute(
                select(Ticket, TicketPanel).join(TicketPanel, Ticket.panel_id == TicketPanel.id).where(
                    Ticket.guild_id.in_(guild_ids), Ticket.status == "open", Ticket.auto_close_disabled.is_(False),
                    TicketPanel.auto_close_hours > 0,
                ).order_by(Ticket.last_activity_at).limit(AUTO_CLOSE_BATCH))).all()
        for ticket, panel in rows:
            if utcnow() - ticket.last_activity_at < timedelta(hours=panel.auto_close_hours):
                continue
            try:
                await self._auto_close_one(ticket, panel)
            except discord.HTTPException:
                log.exception("Error auto-closing ticket %s", ticket.id)

    async def _auto_close_one(self, ticket: Ticket, panel: TicketPanel) -> None:
        guild = self.bot.get_guild(int(ticket.guild_id))
        if guild is None:
            return
        channel = guild.get_channel(int(ticket.channel_id))
        html: str | None = None
        count = 0
        if isinstance(channel, discord.TextChannel) and panel.transcript_enabled:
            try:
                html, count, _ = await self.service.transcript(channel, ticket, "auto-close")
            except discord.HTTPException:
                html = None
        await self.service.update(ticket.id, status="closed", closed_at=utcnow(), closed_by="auto-close",
                                  close_reason="Cierre automático por inactividad")
        self._ticket_channels.delete(ticket.channel_id)
        num = pad(ticket.number)
        if isinstance(channel, discord.TextChannel):
            # The creator keeps read access so they can press "Reabrir".
            member = guild.get_member(int(ticket.user_id))
            try:
                if member is not None:
                    await channel.set_permissions(member, view_channel=True, send_messages=False,
                                                  read_message_history=True)
                else:
                    await channel.set_permissions(discord.Object(int(ticket.user_id)), overwrite=None)
                for uid in ticket.added_users or []:
                    await channel.set_permissions(discord.Object(int(uid)), overwrite=None)
                await self.service.move_to_closed_category(channel, panel.closed_category_id)
                await channel.edit(name=f"cerrado-{num}")
                await channel.send(embed=discord.Embed(
                    color=ERROR, title="Ticket cerrado automáticamente", timestamp=discord.utils.utcnow(),
                    description="El ticket fue cerrado automáticamente por inactividad. ¿Deseas abrirlo nuevamente?"),
                    view=closed_actions())
            except discord.HTTPException:
                log.exception("Failed to update auto-closed ticket channel %s", channel.id)
        if html:
            config = await self.bot.configs.get(guild.id)
            target = text_channel(guild, panel.transcript_channel_id or config.ticket_transcript_channel_id)
            if target is not None:
                embed = discord.Embed(color=0x3498DB, title=f"Transcripción: Ticket #{num}", timestamp=discord.utils.utcnow())
                embed.add_field(name="Cerrado por", value="Auto-cierre (inactividad)", inline=True)
                embed.add_field(name="Mensajes", value=str(count), inline=True)
                try:
                    await target.send(embed=embed, file=self.service.transcript_file(html, ticket.number))
                except discord.HTTPException:
                    pass
            if panel.transcript_dm_user or config.ticket_dm_transcript:
                await self.service._dm(ticket.user_id, discord.Embed(
                    color=0x3498DB, title="Ticket cerrado", timestamp=discord.utils.utcnow(),
                    description=f"Tu ticket #{num} fue cerrado automáticamente por inactividad."),
                    self.service.transcript_file(html, ticket.number))
        log.info("Auto-closed ticket #%s (%s) after %sh inactivity", ticket.number, ticket.guild_id,
                 panel.auto_close_hours)

    @tasks.loop(minutes=30)
    @resilient
    async def cleanup_closed(self) -> None:
        """Archive and delete tickets closed more than 7 days ago (small batches)."""
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        transcripts = select(func.count()).select_from(TicketTranscript).where(
            TicketTranscript.ticket_id == Ticket.id).scalar_subquery()
        async with self.bot.db.session() as session:
            stmt = select(Ticket, transcripts).where(
                Ticket.guild_id.in_(guild_ids), Ticket.status == "closed",
                Ticket.closed_at <= utcnow() - CLOSED_RETENTION,
            )
            if self._protected_ticket_ids:
                stmt = stmt.where(Ticket.id.not_in(self._protected_ticket_ids))
            rows = (await session.execute(stmt.order_by(Ticket.closed_at).limit(CLEANUP_BATCH))).all()
        stats = {"deleted": 0, "archived": 0, "protected": 0, "failed": 0}
        for ticket, transcript_count in rows:
            guild = self.bot.get_guild(int(ticket.guild_id))
            if guild is None:
                stats["failed"] += 1
                continue
            channel = guild.get_channel(int(ticket.channel_id))
            if channel is None:
                await self.service.update(ticket.id, status="deleted")
                stats["deleted"] += 1
                continue
            if not isinstance(channel, discord.TextChannel):
                stats["failed"] += 1
                continue
            if PROTECTED_TICKET_RE.search(f"{channel.name} {channel.topic or ''}"):
                self._protected_ticket_ids.add(ticket.id)
                stats["protected"] += 1
                continue
            try:
                if not transcript_count:
                    await self.service.transcript(channel, ticket, "weekly-cleanup")
                    stats["archived"] += 1
                await channel.delete(reason="Limpieza automática: ticket cerrado hace 7 días")
                await self.service.update(ticket.id, status="deleted")
                stats["deleted"] += 1
            except discord.HTTPException:
                stats["failed"] += 1
                log.exception("Weekly cleanup failed for ticket %s", ticket.id)
            await asyncio.sleep(0.3)
        if rows:
            log.info("Closed-ticket cleanup: %s", stats)

    @tasks.loop(minutes=1)
    @resilient
    async def rotate_images(self) -> None:
        """Rotate gallery images on deployed panel messages (minimum interval: 60s)."""
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        async with self.bot.db.session() as session:
            panels = (await session.execute(select(TicketPanel).where(
                TicketPanel.guild_id.in_(guild_ids), TicketPanel.message_id.is_not(None),
                TicketPanel.channel_id != "0"))).scalars().all()
        groups: dict[str, list[TicketPanel]] = {}
        for panel in panels:
            groups.setdefault(panel.message_id or "", []).append(panel)
        now = time.monotonic()
        for message_id, group in groups.items():
            first = group[0]
            if len(first.group_embed_images or []) <= 1:
                continue
            interval = max(60, first.embed_image_interval or 60)
            if message_id not in self._rotation_last:
                self._rotation_last[message_id] = now
                continue
            if now - self._rotation_last[message_id] < interval:
                continue
            self._rotation_last[message_id] = now
            index = self._rotation_index.get(message_id, 0) + 1
            self._rotation_index[message_id] = index
            channel = self.bot.get_channel(int(first.channel_id))
            if not isinstance(channel, discord.abc.Messageable):
                continue
            try:
                message = await channel.fetch_message(int(message_id))
                ordered = order_panels(group, panel_order_from_components(message.components))
                embed, view = panel_message(ordered, image_index=index)
                await message.edit(embed=embed, view=view)
            except discord.NotFound:
                log.warning("Panel message %s not found, untracking", message_id)
                async with self.bot.db.session() as session:
                    await session.execute(update(TicketPanel).where(
                        TicketPanel.message_id == message_id).values(message_id=None))
            except discord.HTTPException as exc:
                log.error("Failed to rotate image for %s: %s", message_id, exc)

    @auto_close.before_loop
    @cleanup_closed.before_loop
    @rotate_images.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    # ── Dashboard actions (internal API) ─────────────────────────────────

    async def _text_channel_in(self, guild_id: str, channel_id: str) -> discord.TextChannel:
        guild = self.bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
        if guild is None:
            raise HttpError(404, "Servidor no disponible")
        channel = guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
        if channel is None:
            raise HttpError(404, "Canal no encontrado")
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise HttpError(400, "El canal seleccionado no admite mensajes de texto")
        return channel  # type: ignore[return-value]

    async def sync_panel_message(self, guild_id: str, channel_id: str, message_id: str) -> None:
        async with self.bot.db.session() as session:
            group = list((await session.execute(select(TicketPanel).where(
                TicketPanel.guild_id == guild_id, TicketPanel.message_id == message_id,
                TicketPanel.channel_id == channel_id).order_by(TicketPanel.created_at))).scalars().all())
        if not group:
            return
        channel = await self._text_channel_in(guild_id, channel_id)
        message = await channel.fetch_message(int(message_id))
        group = order_panels(group, panel_order_from_components(message.components))
        embed, view = panel_message(group)
        await message.edit(embed=embed, view=view)

    async def _deploy_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        guild_id, channel_id = str(body.get("guildId", "")), str(body.get("channelId", ""))
        panel_ids = [str(p) for p in body.get("panelIds") or []]
        if not is_snowflake(channel_id) or not panel_ids:
            raise HttpError(400, "Se requieren un ID de canal válido y al menos un panel")
        if len(panel_ids) > 5:
            raise HttpError(400, "Cada mensaje de panel admite un máximo de 5 botones")
        channel = await self._text_channel_in(guild_id, channel_id)
        async with self.bot.db.session() as session:
            panels = (await session.execute(select(TicketPanel).where(
                TicketPanel.id.in_(panel_ids), TicketPanel.guild_id == guild_id))).scalars().all()
        ordered = [p for pid in panel_ids for p in panels if p.id == pid]
        if not ordered:
            raise HttpError(404, "No se encontraron paneles")
        images = [str(u) for u in body.get("embedImages") or [] if u]
        embed, view = panel_message(ordered, title=body.get("embedTitle"), description=body.get("embedDescription"),
                                    color=body.get("embedColor"), images=images)
        try:
            message = await channel.send(embed=embed, view=view)
        except discord.HTTPException as exc:
            raise HttpError(502, f"No se pudo enviar el mensaje: {exc.text or exc}") from exc
        try:
            interval = int(body.get("embedImageInterval") or 10)
        except (TypeError, ValueError):
            interval = 10
        async with self.bot.db.session() as session:
            await session.execute(update(TicketPanel).where(TicketPanel.id.in_([p.id for p in ordered])).values(
                channel_id=channel_id, message_id=str(message.id),
                group_embed_title=body.get("embedTitle") or "Sistema de Tickets",
                group_embed_description=body.get("embedDescription") or "",
                group_embed_color=body.get("embedColor") or "#5865F2", group_embed_images=images,
                embed_image_interval=interval))
        self._repost_channels.delete(guild_id)
        return json_response({"success": True, "messageId": str(message.id), "channelId": channel_id,
                              "panelCount": len(ordered)})

    async def _sync_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        async with self.bot.db.session() as session:
            panel = await session.get(TicketPanel, str(body.get("panelId", "")))
        if panel is None or panel.guild_id != str(body.get("guildId")):
            raise HttpError(404, "Panel no encontrado")
        if not panel.message_id or not panel.channel_id or panel.channel_id == "0":
            raise HttpError(400, "El panel todavía no se ha publicado")
        try:
            await self.sync_panel_message(panel.guild_id, panel.channel_id, panel.message_id)
        except discord.HTTPException as exc:
            raise HttpError(502, f"No se pudo actualizar el mensaje: {exc}") from exc
        self._repost_channels.delete(panel.guild_id)
        return json_response({"success": True})

    async def _cross_deploy_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        source_guild, target_guild = str(body.get("guildId", "")), str(body.get("targetGuildId", ""))
        channel_id = str(body.get("channelId", ""))
        source_ids = [str(p) for p in body.get("sourcePanelIds") or []]
        if not (is_snowflake(target_guild) and is_snowflake(channel_id)) or not source_ids:
            raise HttpError(400, "Se requieren el servidor de destino, el canal y al menos un panel de origen")
        if target_guild == source_guild:
            raise HttpError(400, "Usa la publicación normal cuando el servidor de destino sea el mismo servidor")
        if len(source_ids) > 5:
            raise HttpError(400, "Cada mensaje de panel admite un máximo de 5 botones")
        channel = await self._text_channel_in(target_guild, channel_id)
        async with self.bot.db.session() as session:
            sources = (await session.execute(select(TicketPanel).where(
                TicketPanel.id.in_(source_ids), TicketPanel.guild_id == source_guild))).scalars().all()
        ordered = [p for pid in source_ids for p in sources if p.id == pid]
        if not ordered:
            raise HttpError(404, "No source panels found")
        await self.bot.configs.get(target_guild)
        copied_fields = ("name", "title", "description", "embed_color", "footer_text", "button_label", "button_emoji",
                         "button_color", "style", "naming_pattern", "ticket_limit", "mention_staff", "mention_creator",
                         "welcome_title", "welcome_message", "welcome_color")
        copies = [TicketPanel(
            guild_id=target_guild, channel_id=channel_id, **{f: getattr(src, f) for f in copied_fields},
            group_embed_title=body.get("embedTitle") or src.group_embed_title,
            group_embed_description=body["embedDescription"] if body.get("embedDescription") is not None
            else src.group_embed_description,
            group_embed_color=body.get("embedColor") or src.group_embed_color,
        ) for src in ordered]
        async with self.bot.db.session() as session:
            session.add_all(copies)
        embed, view = panel_message(copies, title=body.get("embedTitle"), description=body.get("embedDescription"),
                                    color=body.get("embedColor"))
        try:
            message = await channel.send(embed=embed, view=view)
        except discord.HTTPException as exc:
            async with self.bot.db.session() as session:
                await session.execute(delete(TicketPanel).where(TicketPanel.id.in_([c.id for c in copies])))
            raise HttpError(502, f"No se pudo enviar el mensaje: {exc}") from exc
        async with self.bot.db.session() as session:
            await session.execute(update(TicketPanel).where(
                TicketPanel.id.in_([c.id for c in copies])).values(message_id=str(message.id)))
        return json_response({"success": True, "messageId": str(message.id), "panelCount": len(copies),
                              "targetGuildId": target_guild})

    async def _close_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        found = await self.service.by_channel(int(body.get("channelId") or 0))
        if found is None or found[0].guild_id != str(body.get("guildId")):
            raise HttpError(404, "Ticket no encontrado")
        closed = await self.service.close_by_system(found[0].channel_id, str(body.get("closedBy") or "dashboard"),
                                                    str(body.get("reason") or "Cerrado desde el dashboard"))
        return json_response({"success": closed})

    # ── /ticket ──────────────────────────────────────────────────────────

    ticket = app_commands.Group(name="ticket", description="Comandos del sistema de tickets", guild_only=True,
                                extras={"module": "tickets", "cooldown": 5})

    async def _require_ticket(self, interaction: discord.Interaction, *, open_only: bool = True,
                              message: str = "Este no es un ticket abierto.") -> tuple[Ticket, TicketPanel | None] | None:
        found = await self._context(interaction)
        if found is None or (open_only and found[0].status != "open"):
            await _ephemeral(interaction, message)
            return None
        return found

    async def _require_staff(self, interaction: discord.Interaction, panel: TicketPanel | None) -> bool:
        assert isinstance(interaction.user, discord.Member)
        if await self.service.is_staff(interaction.user, panel):
            return True
        await _ephemeral(interaction, "Solo el staff puede usar esta acción.")
        return False

    @ticket.command(name="panel", description="Crear/enviar un panel de tickets a un canal")
    @app_commands.describe(titulo="Titulo del panel", descripcion="Descripcion del panel", texto_boton="Texto del boton",
                           emoji_boton="Emoji del boton", canal="Canal donde enviar el panel",
                           categoria="Categoria para tickets nuevos", rol_staff="Rol del staff con acceso al ticket",
                           nombre="Nombre interno del panel (para varios paneles)")
    async def cmd_panel(self, interaction: discord.Interaction, titulo: str | None = None,
                        descripcion: str | None = None, texto_boton: str | None = None,
                        emoji_boton: str | None = None, canal: discord.TextChannel | None = None,
                        categoria: discord.CategoryChannel | None = None, rol_staff: discord.Role | None = None,
                        nombre: str | None = None) -> None:
        if not interaction.permissions.manage_guild:
            await _ephemeral(interaction, "Necesitas el permiso de **Gestionar servidor**.")
            return
        target = canal or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await _ephemeral(interaction, "Canal de texto inválido.")
            return
        title = titulo or "Tickets de soporte"
        panel = TicketPanel(
            guild_id=str(interaction.guild_id), name=nombre or title, channel_id=str(target.id), title=title,
            description=descripcion or "Haz clic en el botón de abajo para crear un ticket de soporte.\nUn miembro "
                                       "del staff te ayudará en breve.",
            button_label=texto_boton or "Crear ticket", button_emoji=emoji_boton or "🎫",
            category_id=str(categoria.id) if categoria else None, staff_role_ids=[str(rol_staff.id)] if rol_staff else [],
        )
        async with self.bot.db.session() as session:
            session.add(panel)
        embed = discord.Embed(color=0x5865F2, title=title, description=panel.description,
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text=panel.footer_text or f"{self.bot.settings.display_name} | Sistema de tickets")
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(custom_id=f"{CREATE_PREFIX}{panel.id}", label=panel.button_label,
                                        emoji=parse_emoji(panel.button_emoji), style=discord.ButtonStyle.primary))
        message = await target.send(embed=embed, view=view)
        await self._set_message(panel.id, message.id)
        await _ephemeral(interaction, f"Panel de tickets **{panel.name}** creado en {target.mention}.")

    async def _set_message(self, panel_id: str, message_id: int) -> None:
        async with self.bot.db.session() as session:
            await session.execute(update(TicketPanel).where(TicketPanel.id == panel_id).values(message_id=str(message_id)))

    @ticket.command(name="cerrar", description="Cerrar el ticket actual")
    @app_commands.describe(motivo="Motivo del cierre")
    async def cmd_close(self, interaction: discord.Interaction, motivo: str) -> None:
        found = await self._require_ticket(interaction, message="Este no es un canal de ticket abierto.")
        if found is None:
            return
        ticket, panel = found
        assert isinstance(interaction.user, discord.Member) and isinstance(interaction.channel, discord.TextChannel)
        if not await self.service.can_close(interaction.user, ticket, panel):
            await _ephemeral(interaction, "Solo puede cerrar este ticket la persona que lo abrió o el staff.")
            return
        await interaction.response.defer()
        embed = await self.service.close(interaction.channel, ticket, panel, str(interaction.user.id), motivo)
        self._ticket_channels.delete(str(interaction.channel.id))
        await interaction.followup.send(embed=embed, view=closed_actions())
        notice = discord.Embed(color=ERROR, title="Tu ticket fue cerrado", timestamp=discord.utils.utcnow(),
                               description=f"Tu ticket **#{pad(ticket.number)}** en **{interaction.guild.name}** fue cerrado.")  # type: ignore[union-attr]
        notice.add_field(name="Motivo", value=motivo)
        await self.service._dm(ticket.user_id, notice)

    @ticket.command(name="solicitar-cierre", description="Enviar una solicitud de cierre al creador del ticket")
    @app_commands.describe(motivo="Motivo de la solicitud de cierre")
    async def cmd_close_request(self, interaction: discord.Interaction, motivo: str | None = None) -> None:
        if await self._require_ticket(interaction) is None:
            return
        description = f"{interaction.user.mention} solicitó cerrar este ticket."
        if motivo:
            description += f"\n**Motivo:** {motivo}"
        description += "\n\nHaz clic en el botón de abajo para confirmar o cancelar."
        await interaction.response.send_message(
            embed=discord.Embed(color=WARN, title="Solicitud de cierre", description=description,
                                timestamp=discord.utils.utcnow()),
            view=close_confirmation(interaction.user.id, cancel_label="Mantener abierto", confirm_label="Cerrar ticket"))

    @ticket.command(name="reabrir", description="Reabrir un ticket cerrado")
    async def cmd_reopen(self, interaction: discord.Interaction) -> None:
        found = await self._require_ticket(interaction, open_only=False, message="Este ticket no está cerrado.")
        if found is None:
            return
        ticket, panel = found
        if ticket.status != "closed":
            await _ephemeral(interaction, "Este ticket no está cerrado.")
            return
        if not await self._reopen_allowed(interaction, ticket, panel):
            return
        assert isinstance(interaction.channel, discord.TextChannel)
        await interaction.response.defer()
        embed = await self.service.reopen(interaction.channel, ticket, panel, interaction.user)
        self._ticket_channels.delete(str(interaction.channel.id))
        await interaction.followup.send(embed=embed, view=ticket_actions(panel, ticket))

    @ticket.command(name="eliminar", description="Eliminar el canal del ticket actual")
    async def cmd_delete(self, interaction: discord.Interaction) -> None:
        await self.service.delete(interaction)

    @ticket.command(name="transcripcion", description="Generar una transcripcion HTML de este ticket")
    async def cmd_transcript(self, interaction: discord.Interaction) -> None:
        found = await self._require_ticket(interaction, open_only=False, message="Este no es un canal de ticket.")
        if found is None:
            return
        _, panel = found
        if panel is None or not panel.transcript_enabled:
            await _ephemeral(interaction, "Las transcripciones estan desactivadas en este servidor.")
            return
        if not await self._require_staff(interaction, panel):
            return
        await self.on_transcript(interaction)

    @ticket.command(name="agregar", description="Agregar un usuario al ticket actual")
    @app_commands.describe(usuario="Usuario a agregar")
    async def cmd_add(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        found = await self._require_ticket(interaction)
        if found is None:
            return
        ticket, _ = found
        assert isinstance(interaction.channel, discord.TextChannel)
        await interaction.channel.set_permissions(usuario, view_channel=True, send_messages=True,
                                                  read_message_history=True, attach_files=True)
        if str(usuario.id) not in (ticket.added_users or []):
            await self.service.update(ticket.id, added_users=[*(ticket.added_users or []), str(usuario.id)])
        await interaction.response.send_message(embed=discord.Embed(
            color=OK, description=f"{usuario.mention} fue agregado a este ticket.", timestamp=discord.utils.utcnow()))

    @ticket.command(name="quitar", description="Quitar un usuario del ticket actual")
    @app_commands.describe(usuario="Usuario a quitar")
    async def cmd_remove(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        found = await self._require_ticket(interaction, open_only=False, message="Este no es un canal de ticket.")
        if found is None:
            return
        ticket, _ = found
        assert isinstance(interaction.channel, discord.TextChannel)
        await interaction.channel.set_permissions(usuario, overwrite=None)
        await self.service.update(ticket.id, added_users=[u for u in ticket.added_users or [] if u != str(usuario.id)])
        await interaction.response.send_message(embed=discord.Embed(
            color=ERROR, description=f"{usuario.mention} fue quitado de este ticket.", timestamp=discord.utils.utcnow()))

    @ticket.command(name="asignar", description="Asignarte este ticket como staff")
    async def cmd_claim(self, interaction: discord.Interaction) -> None:
        found = await self._require_ticket(interaction)
        if found is None:
            return
        ticket, panel = found
        await self._claim(interaction, ticket, panel, "Este ticket ya está asignado a <@{}>.",
                          "Solo el staff puede asignarse tickets.", "Este ticket fue asignado a {}.")

    @ticket.command(name="desasignar", description="Liberar tu asignacion de este ticket")
    async def cmd_unclaim(self, interaction: discord.Interaction) -> None:
        found = await self._require_ticket(interaction)
        if found is None:
            return
        ticket, panel = found
        if not ticket.claimed_by:
            await _ephemeral(interaction, "Este ticket no está asignado.")
            return
        if ticket.claimed_by != str(interaction.user.id) and not interaction.permissions.manage_guild:
            await _ephemeral(interaction, "Solo puedes desasignar tickets que tú asignaste o tener el permiso de "
                                          "Gestionar servidor.")
            return
        assert isinstance(interaction.channel, discord.TextChannel)
        if panel is not None and panel.claim_lock_others:
            for rid in panel.staff_role_ids or []:
                role = interaction.channel.guild.get_role(int(rid)) if rid.isdigit() else None
                if role is not None:
                    try:
                        await interaction.channel.set_permissions(role, view_channel=True, send_messages=True,
                                                                  read_message_history=True, attach_files=True)
                    except discord.HTTPException:
                        pass
        await self.service.update(ticket.id, claimed_by=None)
        await interaction.response.send_message(embed=discord.Embed(
            color=0x3498DB, description="Este ticket ya no está asignado.", timestamp=discord.utils.utcnow()))

    @ticket.command(name="renombrar", description="Renombrar el canal del ticket actual")
    @app_commands.describe(nombre="Nuevo nombre del canal")
    async def cmd_rename(self, interaction: discord.Interaction, nombre: str) -> None:
        if await self._require_ticket(interaction, open_only=False, message="Este no es un canal de ticket.") is None:
            return
        assert isinstance(interaction.channel, discord.TextChannel)
        await interaction.channel.edit(name=nombre[:100])
        await interaction.response.send_message(embed=discord.Embed(
            color=0x3498DB, description=f"Canal del ticket renombrado a **{nombre[:100]}**.",
            timestamp=discord.utils.utcnow()))

    @ticket.command(name="prioridad", description="Definir prioridad del ticket")
    @app_commands.describe(nivel="Nivel de prioridad")
    @app_commands.choices(nivel=PRIORITY_CHOICES)
    async def cmd_priority(self, interaction: discord.Interaction, nivel: str) -> None:
        found = await self._require_ticket(interaction, open_only=False, message="Este no es un canal de ticket.")
        if found is None:
            return
        await self.service.update(found[0].id, priority=nivel)
        await interaction.response.send_message(embed=discord.Embed(
            color=PRIORITY_COLORS.get(nivel, INFO), timestamp=discord.utils.utcnow(),
            description=f"{PRIORITY_EMOJI.get(nivel, '')} Prioridad del ticket definida en **{nivel.upper()}**."))

    @ticket.command(name="escalar", description="Escalar este ticket a otro panel/equipo")
    @app_commands.describe(nombre_panel="Nombre del panel destino")
    async def cmd_escalate(self, interaction: discord.Interaction, nombre_panel: str) -> None:
        found = await self._require_ticket(interaction)
        if found is None:
            return
        ticket, panel = found
        async with self.bot.db.session() as session:
            target = (await session.execute(select(TicketPanel).where(
                TicketPanel.guild_id == str(interaction.guild_id),
                func.lower(TicketPanel.name) == nombre_panel.lower()).limit(1))).scalar_one_or_none()
        if target is None:
            await _ephemeral(interaction, f'No se encontró el panel "{nombre_panel}".')
            return
        if target.id == ticket.panel_id:
            await _ephemeral(interaction, "El ticket ya está en este panel.")
            return
        await self.service.update(ticket.id, panel_id=target.id)
        channel = interaction.channel
        assert isinstance(channel, discord.TextChannel)
        await interaction.response.defer()
        for rid in (panel.staff_role_ids if panel else []) or []:
            if rid.isdigit():
                try:
                    await channel.set_permissions(discord.Object(int(rid)), overwrite=None)
                except discord.HTTPException:
                    pass
        for rid in target.staff_role_ids or []:
            role = channel.guild.get_role(int(rid)) if rid.isdigit() else None
            if role is not None:
                try:
                    await channel.set_permissions(role, view_channel=True, send_messages=True,
                                                  read_message_history=True, attach_files=True)
                except discord.HTTPException:
                    pass
        if target.category_id and target.category_id != (panel.category_id if panel else None):
            category = channel.guild.get_channel(int(target.category_id)) if target.category_id.isdigit() else None
            if isinstance(category, discord.CategoryChannel):
                try:
                    await channel.edit(category=category, sync_permissions=False)
                except discord.HTTPException:
                    pass
        mentions = " ".join(f"<@&{rid}>" for rid in target.staff_role_ids or [])
        await interaction.followup.send(content=mentions or None, embed=discord.Embed(
            color=0xF47B67, title="Ticket escalado", timestamp=discord.utils.utcnow(),
            description=f"Este ticket fue escalado a **{target.name or target.title}** por {interaction.user.mention}."),
            allowed_mentions=discord.AllowedMentions(roles=True))

    @ticket.command(name="nuevo", description="Crear un ticket nuevo por comando")
    @app_commands.describe(tema="Tema/motivo del ticket")
    async def cmd_new(self, interaction: discord.Interaction, tema: str | None = None) -> None:
        async with self.bot.db.session() as session:
            panels = list((await session.execute(select(TicketPanel).where(
                TicketPanel.guild_id == str(interaction.guild_id)).order_by(TicketPanel.created_at))).scalars().all())
        if not panels:
            await _ephemeral(interaction, "No hay paneles de tickets configurados. Un admin debe crear uno primero "
                                          "con `/ticket panel`.")
            return
        if len(panels) == 1:
            panel = panels[0]
            existing = await self.service.open_tickets(interaction.guild_id or 0, interaction.user.id, panel.id)
            if len(existing) >= (panel.ticket_limit or 1):
                await _ephemeral(interaction, f"Ya tienes un ticket abierto. <#{existing[0].channel_id}>")
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            await self.service.create(interaction, panel, options=CreateOptions(
                topic=tema, extra_fields=[("Tema", tema)] if tema else [],
                reply_content="Ticket creado: {channel}"))
            return
        select_menu = discord.ui.Select(custom_id="ticket_panel_select",
                                        placeholder="Selecciona una categoria de ticket...")
        for p in panels[:25]:
            select_menu.add_option(label=(p.name or p.title)[:100], value=p.id,
                                   description=(p.description or "Crear un ticket")[:100],
                                   emoji=parse_emoji(p.button_emoji or "🎫"))
        view = discord.ui.View()
        view.add_item(select_menu)
        await interaction.response.send_message("Selecciona una categoria de ticket:", view=view, ephemeral=True)

    async def _preset(self, interaction: discord.Interaction, prefix: str, title: str,
                      canal: discord.TextChannel | None, transcripts: discord.TextChannel | None,
                      categories: dict[str, discord.CategoryChannel | None], staff: discord.Role | None) -> None:
        if not interaction.permissions.manage_guild:
            await _ephemeral(interaction, "Necesitas el permiso de **Gestionar servidor**.")
            return
        target = canal or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await _ephemeral(interaction, "Canal de texto inválido.")
            return
        panels = [TicketPanel(
            guild_id=str(interaction.guild_id), name=f"{prefix}-{name}", channel_id=str(target.id), title=label,
            description=label, button_label=label, button_emoji=emoji, button_color=style,
            category_id=str(categories[cat].id) if categories.get(cat) else None,  # type: ignore[union-attr]
            staff_role_ids=[str(staff.id)] if staff else [],
            transcript_channel_id=str(transcripts.id) if transcripts else None, auto_close_hours=24,
            welcome_message=welcome,
        ) for name, label, emoji, style, cat, welcome in PRESET_TYPES]
        async with self.bot.db.session() as session:
            session.add_all(panels)
        embed = discord.Embed(color=0x2B2D31, title="SELECCIONAR EL BOTÓN QUE CORRESPONDA A TU CASO",
                              description=PRESET_DESCRIPTION)
        _, view = panel_message(panels)
        message = await target.send(embed=embed, view=view)
        async with self.bot.db.session() as session:
            await session.execute(update(TicketPanel).where(
                TicketPanel.id.in_([p.id for p in panels])).values(message_id=str(message.id)))
        await _ephemeral(interaction, f"Panel **{title}** creado en {target.mention} con 4 tipos de ticket.")

    @ticket.command(name="hubstore",
                    description="Crear el panel de Hub Store con botones de Mediación, Soporte, Verificación OOC y Estafas")
    @app_commands.describe(canal="Canal donde enviar el panel", canal_transcripcion="Canal de transcripciones de tickets",
                           categoria_mediacion="Categoría Tickets Mediacion", categoria_soporte="Categoría Tickets Soporte",
                           categoria_verificacion="Categoría Tickets Verificacion",
                           categoria_estafas="Categoría Tickets Estafas", rol_staff="Rol del staff con acceso a los tickets")
    async def cmd_hubstore(self, interaction: discord.Interaction, canal: discord.TextChannel | None = None,
                           canal_transcripcion: discord.TextChannel | None = None,
                           categoria_mediacion: discord.CategoryChannel | None = None,
                           categoria_soporte: discord.CategoryChannel | None = None,
                           categoria_verificacion: discord.CategoryChannel | None = None,
                           categoria_estafas: discord.CategoryChannel | None = None,
                           rol_staff: discord.Role | None = None) -> None:
        await self._preset(interaction, "hubstore", "Hub Store", canal, canal_transcripcion, {
            "categoria_mediacion": categoria_mediacion, "categoria_soporte": categoria_soporte,
            "categoria_verificacion": categoria_verificacion, "categoria_estafas": categoria_estafas}, rol_staff)

    @ticket.command(name="vapiano",
                    description="Crear el panel de Vapiano con botones de Mediación, Soporte, Verificación OOC y Estafas")
    @app_commands.describe(canal="Canal donde enviar el panel", canal_transcripcion="Canal de transcripciones de tickets",
                           categoria_mediacion="Categoría Tickets Mediacion", categoria_soporte="Categoría Tickets Soporte",
                           categoria_verificacion="Categoría Tickets Verificacion",
                           categoria_estafas="Categoría Tickets Estafas", rol_staff="Rol del staff con acceso a los tickets")
    async def cmd_vapiano(self, interaction: discord.Interaction, canal: discord.TextChannel | None = None,
                          canal_transcripcion: discord.TextChannel | None = None,
                          categoria_mediacion: discord.CategoryChannel | None = None,
                          categoria_soporte: discord.CategoryChannel | None = None,
                          categoria_verificacion: discord.CategoryChannel | None = None,
                          categoria_estafas: discord.CategoryChannel | None = None,
                          rol_staff: discord.Role | None = None) -> None:
        await self._preset(interaction, "vapiano", "Vapiano", canal, canal_transcripcion, {
            "categoria_mediacion": categoria_mediacion, "categoria_soporte": categoria_soporte,
            "categoria_verificacion": categoria_verificacion, "categoria_estafas": categoria_estafas}, rol_staff)

    # New in v2 (Ticket King-style): staff overview commands.

    @ticket.command(name="estadisticas", description="Ver estadísticas del sistema de tickets (staff)")
    async def cmd_stats(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.user, discord.Member)
        if not await self._require_staff(interaction, None):
            return
        stats = await self.service.stats(interaction.guild_id or 0)
        embed = discord.Embed(color=INFO, title="📊 Estadísticas de tickets", timestamp=discord.utils.utcnow())
        embed.add_field(name="Abiertos", value=str(stats["open"]), inline=True)
        embed.add_field(name="Cerrados", value=str(stats["closed"]), inline=True)
        embed.add_field(name="Total", value=str(stats["total"]), inline=True)
        embed.add_field(name="Esta semana", value=str(stats["thisWeek"]), inline=True)
        embed.add_field(name="Valoración media",
                        value=f"{stats['avgRating']} ⭐" if stats["avgRating"] is not None else "Sin datos", inline=True)
        first = stats["avgFirstResponseSeconds"]
        embed.add_field(name="Primera respuesta media", value=format_duration(first) if first else "Sin datos",
                        inline=True)
        priorities = stats["openByPriority"]
        if priorities:
            embed.add_field(name="Abiertos por prioridad", inline=False, value=" · ".join(
                f"{PRIORITY_EMOJI.get(p, '')} {p}: **{n}**" for p, n in
                sorted(priorities.items(), key=lambda item: PRIORITY_ORDER.get(item[0], 9))))
        if stats["topClaimers"]:
            embed.add_field(name="Staff con más tickets", inline=False, value="\n".join(
                f"**{i}.** <@{uid}> — {n}" for i, (uid, n) in enumerate(stats["topClaimers"], 1)))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket.command(name="lista", description="Listar los tickets abiertos ordenados por prioridad (staff)")
    async def cmd_list(self, interaction: discord.Interaction) -> None:
        if not await self._require_staff(interaction, None):
            return
        async with self.bot.db.session() as session:
            tickets = (await session.execute(select(Ticket).where(
                Ticket.guild_id == str(interaction.guild_id), Ticket.status == "open"))).scalars().all()
        if not tickets:
            await _ephemeral(interaction, "No hay tickets abiertos. 🎉")
            return
        ordered = sorted(tickets, key=lambda t: (PRIORITY_ORDER.get(t.priority, 9), t.created_at))[:25]
        lines = [
            f"{PRIORITY_EMOJI.get(t.priority, '🔵')} <#{t.channel_id}> · <@{t.user_id}> · {discord_ts(t.created_at)}"
            f"{f' · 🙋 <@{t.claimed_by}>' if t.claimed_by else ''}"
            for t in ordered
        ]
        embed = discord.Embed(color=INFO, title=f"🎫 Tickets abiertos ({len(tickets)})", description="\n".join(lines),
                              timestamp=discord.utils.utcnow())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Tickets(bot))
