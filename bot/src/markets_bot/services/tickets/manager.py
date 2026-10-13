"""Ticket lifecycle: create, close, reopen, delete, claim, transcripts and logs."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from sqlalchemy import func, select, update

from markets_bot.core.audit import send_to, text_channel
from markets_bot.core.utils import ERROR, INFO, OK, parse_color, utcnow
from markets_bot.db.models import GuildConfig, Ticket, TicketPanel, TicketTranscript
from markets_bot.services.tickets import transcript as transcripts
from markets_bot.services.tickets.ui import closed_actions, feedback_view, pad, ticket_actions

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

TRANSCRIPT_BLUE = 0x3498DB
CLOSED_CATEGORY_LIMIT = 50
_ALLOW_MEMBER = discord.PermissionOverwrite(
    view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True)
_ALLOW_STAFF = discord.PermissionOverwrite(
    view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
_ALLOW_BOT = discord.PermissionOverwrite(
    view_channel=True, send_messages=True, manage_channels=True, read_message_history=True, manage_messages=True)


@dataclass(slots=True)
class CreateOptions:
    """Per-call overrides (shop / rifa tickets reuse the panel flow with their own text)."""

    category_id: str | None = None
    staff_role_ids: list[str] = field(default_factory=list)
    naming_pattern: str | None = None
    topic: str | None = None
    welcome_title: str | None = None
    welcome_message: str | None = None
    welcome_color: str | None = None
    image_urls: list[str] = field(default_factory=list)
    reply_content: str | None = None
    source_label: str | None = None
    participant_user_ids: list[str] = field(default_factory=list)
    mention_user_ids: list[str] | None = None
    extra_fields: list[tuple[str, str]] = field(default_factory=list)


def channel_name(pattern: str, number: int, username: str, display_name: str, user_id: int) -> str:
    value = (pattern.replace("{number}", pad(number)).replace("{username}", username)
             .replace("{displayname}", display_name).replace("{userid}", str(user_id)))
    value = unicodedata.normalize("NFD", value.lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")[:90]
    return value or f"ticket-{pad(number)}"


def open_duration(created_at: Any) -> str:
    minutes = int((utcnow() - created_at).total_seconds() // 60)
    hours, minutes = divmod(max(0, minutes), 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


class TicketService:
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot

    # ── Lookups ──────────────────────────────────────────────────────────

    async def panel(self, panel_id: str) -> TicketPanel | None:
        async with self.bot.db.session() as session:
            return await session.get(TicketPanel, panel_id)

    async def by_channel(self, channel_id: int) -> tuple[Ticket, TicketPanel | None] | None:
        async with self.bot.db.session() as session:
            ticket = (await session.execute(
                select(Ticket).where(Ticket.channel_id == str(channel_id)))).scalar_one_or_none()
            if ticket is None:
                return None
            panel = await session.get(TicketPanel, ticket.panel_id) if ticket.panel_id else None
            return ticket, panel

    async def open_tickets(self, guild_id: int, user_id: int, panel_id: str) -> list[Ticket]:
        async with self.bot.db.session() as session:
            return list((await session.execute(select(Ticket).where(
                Ticket.guild_id == str(guild_id), Ticket.user_id == str(user_id), Ticket.panel_id == panel_id,
                Ticket.status == "open").order_by(Ticket.created_at.desc()))).scalars().all())

    async def update(self, ticket_id: str, **values: Any) -> None:
        async with self.bot.db.session() as session:
            await session.execute(update(Ticket).where(Ticket.id == ticket_id).values(**values))

    async def staff_roles(self, guild_id: int, panel: TicketPanel | None) -> list[str]:
        if panel and panel.staff_role_ids:
            return list(panel.staff_role_ids)
        return list((await self.bot.configs.get(guild_id)).ticket_staff_role_ids or [])

    async def is_staff(self, member: discord.Member, panel: TicketPanel | None) -> bool:
        roles = {str(r.id) for r in member.roles}
        staff = set(await self.staff_roles(member.guild.id, panel))
        admins = set(panel.admin_role_ids or []) if panel else set()
        perms = member.guild_permissions
        return bool(roles & (staff | admins)) or perms.manage_channels or perms.manage_guild or perms.administrator

    async def can_close(self, member: discord.Member, ticket: Ticket, panel: TicketPanel | None) -> bool:
        return str(member.id) == ticket.user_id or await self.is_staff(member, panel)

    async def log(self, guild: discord.Guild, panel: TicketPanel | None, embed: discord.Embed,
                  file: discord.File | None = None) -> None:
        config = await self.bot.configs.get(guild.id)
        channel_id = (panel.log_channel_id if panel else None) or config.ticket_log_channel_id
        kwargs: dict[str, Any] = {"embed": embed}
        if file is not None:
            kwargs["file"] = file
        await send_to(guild, channel_id, **kwargs)

    # ── Create ───────────────────────────────────────────────────────────

    async def next_number(self, guild_id: int) -> int:
        await self.bot.configs.get(guild_id)  # ensure the config row exists
        async with self.bot.db.session() as session:
            number = (await session.execute(
                update(GuildConfig).where(GuildConfig.id == str(guild_id))
                .values(ticket_counter=GuildConfig.ticket_counter + 1).returning(GuildConfig.ticket_counter)
            )).scalar_one()
        self.bot.configs.invalidate(guild_id)
        return int(number)

    async def create(
        self, interaction: discord.Interaction, panel: TicketPanel,
        form_answers: list[dict[str, str]] | None = None, options: CreateOptions | None = None,
    ) -> discord.TextChannel | None:
        """Create a ticket for ``interaction.user``. The interaction must already be deferred (ephemeral)."""
        opts = options or CreateOptions()
        guild = interaction.guild
        user = interaction.user
        if guild is None:
            return None
        try:
            limit = max(1, panel.ticket_limit or 1)
            existing = await self.open_tickets(guild.id, user.id, panel.id)
            if len(existing) >= limit:
                await interaction.edit_original_response(content=(
                    f"Ya tienes {len(existing)} ticket(s) abierto(s) para este panel (límite: {limit}). "
                    f"Ve a <#{existing[0].channel_id}>."))
                return None

            config = await self.bot.configs.get(guild.id)
            number = await self.next_number(guild.id)
            staff_ids = opts.staff_role_ids or await self.staff_roles(guild.id, panel)
            category_id = opts.category_id or panel.category_id or config.ticket_category_id
            category = guild.get_channel(int(category_id)) if category_id and category_id.isdigit() else None
            participants = [
                uid for uid in dict.fromkeys(opts.participant_user_ids)
                if uid.isdigit() and 17 <= len(uid) <= 20 and uid != str(user.id)
            ]

            overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: _ALLOW_MEMBER,
                guild.me: _ALLOW_BOT,
            }
            for uid in participants:
                overwrites[discord.Object(int(uid))] = _ALLOW_MEMBER
            for rid in staff_ids:
                role = guild.get_role(int(rid)) if rid.isdigit() else None
                if role is not None:
                    overwrites[role] = _ALLOW_STAFF

            pattern = opts.naming_pattern or panel.naming_pattern or "ticket-{number}"
            panel_name = panel.name or panel.title
            channel = await guild.create_text_channel(
                channel_name(pattern, number, user.name[:20], user.display_name[:20], user.id),
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,  # type: ignore[arg-type]
                topic=opts.topic or f"Ticket #{number} | Creado por {user.name} | Panel: {panel_name}",
            )
            ticket = Ticket(
                guild_id=str(guild.id), panel_id=panel.id, channel_id=str(channel.id), user_id=str(user.id),
                number=number, status="open", topic=opts.topic, added_users=participants,
                form_answers=form_answers or None,
            )
            async with self.bot.db.session() as session:
                session.add(ticket)

            num = pad(number)

            def fill(text: str, mention: bool) -> str:
                return (text.replace("{user}", user.mention if mention else user.name, 1)
                        .replace("{number}", num, 1).replace("{panel}", panel_name, 1))

            welcome = discord.Embed(
                color=parse_color(opts.welcome_color or panel.welcome_color, INFO),
                title=fill(opts.welcome_title or panel.welcome_title or f"Ticket #{num}", mention=False),
                description=fill(opts.welcome_message or panel.welcome_message or (
                    f"¡Hola {user.mention}! 👋\nUn miembro del staff te atenderá en breve.\n"
                    "Mientras tanto, describe tu consulta con el mayor detalle posible."), mention=True),
                timestamp=discord.utils.utcnow(),
            )
            welcome.set_author(name=guild.name, icon_url=guild.icon.with_size(64).url if guild.icon else None)
            welcome.set_thumbnail(url=user.display_avatar.with_size(128).url)
            for name, value in opts.extra_fields:
                welcome.add_field(name=name, value=value[:1024], inline=False)
            images = [u for u in opts.image_urls if u][:10]
            if images:
                welcome.set_image(url=images[0])
            embeds = [welcome, *(discord.Embed().set_image(url=u) for u in images[1:])]

            mentions: list[str] = []
            if panel.mention_creator:
                mentions.append(user.mention)
            if panel.mention_staff:
                mentions.extend(f"<@&{rid}>" for rid in staff_ids)
            for uid in dict.fromkeys(opts.mention_user_ids if opts.mention_user_ids is not None else participants):
                if uid.isdigit() and uid != str(user.id):
                    mentions.append(f"<@{uid}>")
            await channel.send(content=" ".join(mentions) or None, embeds=embeds, view=ticket_actions(panel, ticket),
                               allowed_mentions=discord.AllowedMentions(users=True, roles=True))

            if form_answers:
                form = discord.Embed(color=INFO, title="📋 Información del ticket", timestamp=discord.utils.utcnow())
                form.set_thumbnail(url=user.display_avatar.with_size(128).url)
                for answer in form_answers[:25]:
                    form.add_field(name=answer["question"][:256], value=answer["answer"][:1024] or "(Sin respuesta)",
                                   inline=False)
                form.set_footer(text=f"Enviado por {user.name}")
                await channel.send(embed=form)

            reply = (opts.reply_content or "Tu ticket ha sido creado: {channel}").replace(
                "{channel}", channel.mention).replace("{number}", num)
            await interaction.edit_original_response(content=reply)

            log_embed = discord.Embed(color=OK, title="Ticket creado", timestamp=discord.utils.utcnow())
            log_embed.add_field(name="Ticket", value=f"#{num} ({channel.mention})", inline=True)
            log_embed.add_field(name="Usuario", value=f"{user.mention} ({user.name})", inline=True)
            log_embed.add_field(name="Panel", value=panel_name, inline=True)
            if opts.source_label:
                log_embed.add_field(name="Origen", value=opts.source_label, inline=True)
            await self.log(guild, panel, log_embed)
            return channel
        except discord.HTTPException:
            log.exception("Error creating ticket in %s", guild.id)
            try:
                await interaction.edit_original_response(
                    content="No se pudo crear el ticket. Intenta de nuevo o contacta a un admin.")
            except discord.HTTPException:
                pass
            return None

    # ── Transcripts ──────────────────────────────────────────────────────

    async def transcript(self, channel: discord.TextChannel, ticket: Ticket,
                         closed_by: str | None) -> tuple[str, int, str]:
        """Fetch history, render HTML and persist it. Returns (html, message count, transcript id)."""
        records = await transcripts.fetch_messages(channel)
        html = transcripts.render_html(records, number=ticket.number, guild_name=channel.guild.name,
                                       channel_name=channel.name, created_at=ticket.created_at,
                                       closed_at=ticket.closed_at or utcnow())
        row = TicketTranscript(ticket_id=ticket.id, panel_id=ticket.panel_id, guild_id=ticket.guild_id,
                               channel_id=str(channel.id), user_id=ticket.user_id, closed_by=closed_by,
                               message_count=len(records), messages=records, html_content=html)
        async with self.bot.db.session() as session:
            session.add(row)
        return html, len(records), row.id

    @staticmethod
    def transcript_file(html: str, number: int) -> discord.File:
        return discord.File(io.BytesIO(html.encode()), filename=f"transcript-{pad(number)}.html")

    # ── Close ────────────────────────────────────────────────────────────

    async def move_to_closed_category(self, channel: discord.TextChannel, category_id: str | None) -> None:
        """Move into the closed category, creating "<name> 2", "<name> 3"... when one is full (50 channels)."""
        if not category_id or not category_id.isdigit():
            return
        guild = channel.guild
        base = guild.get_channel(int(category_id))
        if not isinstance(base, discord.CategoryChannel):
            log.warning("Closed category %s not found in %s", category_id, guild.id)
            return
        base_name = re.sub(r"\s+\d+$", "", base.name)

        def number(name: str) -> int | None:
            if name == base_name:
                return 1
            suffix = name[len(base_name) + 1:]
            return int(suffix) if name.startswith(base_name + " ") and suffix.isdigit() else None

        candidates = sorted(
            (c for c in guild.categories if number(c.name) is not None), key=lambda c: number(c.name) or 0)
        target = next((c for c in candidates if len(c.channels) < CLOSED_CATEGORY_LIMIT), None)
        if target is None:
            used = {number(c.name) for c in candidates}
            next_number = 2
            while next_number in used:
                next_number += 1
            target = await guild.create_category(
                f"{base_name} {next_number}", overwrites=base.overwrites, position=base.position + 1,
                reason="La categoría de tickets cerrados estaba llena")
            log.info("Created overflow closed category %s in %s", target.name, guild.id)
        await channel.edit(category=target, sync_permissions=False)

    async def _revoke(self, channel: discord.TextChannel, user_id: str) -> None:
        overwrite_target = discord.Object(int(user_id))
        if channel.overwrites_for(overwrite_target).is_empty():  # type: ignore[arg-type]
            return
        try:
            await channel.set_permissions(overwrite_target, overwrite=None, reason="Acceso de ticket retirado")
        except discord.NotFound:
            pass

    async def close(self, channel: discord.TextChannel, ticket: Ticket, panel: TicketPanel | None,
                    closed_by: str, reason: str | None) -> discord.Embed:
        guild = channel.guild
        config = await self.bot.configs.get(guild.id)
        html: str | None = None
        count = 0
        if panel is not None and panel.transcript_enabled:
            try:
                html, count, _ = await self.transcript(channel, ticket, closed_by)
            except discord.HTTPException:
                log.exception("Transcript generation failed for ticket %s", ticket.id)

        await self.update(ticket.id, status="closed", closed_at=utcnow(), closed_by=closed_by, close_reason=reason)
        try:
            await self._revoke(channel, ticket.user_id)
            for uid in ticket.added_users or []:
                await self._revoke(channel, uid)
            await channel.edit(name=f"cerrado-{pad(ticket.number)}")
            await self.move_to_closed_category(channel, panel.closed_category_id if panel else None)
        except discord.HTTPException:
            log.exception("Error updating closed ticket channel %s", channel.id)

        duration = open_duration(ticket.created_at)
        description = f"Este ticket fue cerrado por <@{closed_by}>."
        if reason:
            description += f"\n**Motivo:** {reason}"
        description += f"\n**Tiempo abierto:** {duration}"
        if html:
            description += f"\n\nTranscripción guardada ({count} mensajes)."
        closed_embed = discord.Embed(color=ERROR, title="Ticket cerrado", description=description,
                                     timestamp=discord.utils.utcnow())
        num = pad(ticket.number)
        panel_name = (panel.name or panel.title) if panel else "Predeterminado"

        if html:
            transcript_channel = text_channel(guild, (panel.transcript_channel_id if panel else None)
                                              or config.ticket_transcript_channel_id)
            if transcript_channel is not None:
                embed = discord.Embed(color=TRANSCRIPT_BLUE, title=f"Transcripción: Ticket #{num}",
                                      timestamp=discord.utils.utcnow())
                embed.add_field(name="Creado por", value=f"<@{ticket.user_id}>", inline=True)
                embed.add_field(name="Cerrado por", value=f"<@{closed_by}>", inline=True)
                embed.add_field(name="Mensajes", value=str(count), inline=True)
                embed.add_field(name="Panel", value=panel_name, inline=True)
                if reason:
                    embed.add_field(name="Motivo", value=reason, inline=True)
                try:
                    await transcript_channel.send(embed=embed, file=self.transcript_file(html, ticket.number))
                except discord.HTTPException as exc:
                    log.error("Failed to send transcript: %s", exc)
            if panel is not None and panel.transcript_dm_user:
                await self._dm(ticket.user_id, discord.Embed(
                    color=TRANSCRIPT_BLUE, title="Ticket cerrado", timestamp=discord.utils.utcnow(),
                    description=f"Tu ticket #{num} en **{guild.name}** fue cerrado. La transcripción está adjunta abajo."),
                    self.transcript_file(html, ticket.number))
            if panel is not None and panel.transcript_dm_staff and ticket.claimed_by:
                await self._dm(ticket.claimed_by, discord.Embed(
                    color=TRANSCRIPT_BLUE, title="Ticket cerrado — Transcripción", timestamp=discord.utils.utcnow(),
                    description=f"El ticket #{num} que reclamaste fue cerrado."), self.transcript_file(html, ticket.number))

        log_embed = discord.Embed(color=ERROR, title="Ticket cerrado", timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Ticket", value=f"#{num}", inline=True)
        log_embed.add_field(name="Cerrado por", value=f"<@{closed_by}>" if closed_by.isdigit() else closed_by, inline=True)
        log_embed.add_field(name="Tiempo abierto", value=duration, inline=True)
        log_embed.add_field(name="Mensajes", value=str(count) if html else "?", inline=True)
        log_embed.add_field(name="Motivo", value=reason or "Sin motivo", inline=True)
        await self.log(guild, panel, log_embed)

        if panel is not None and panel.feedback_enabled:
            feedback = discord.Embed(color=INFO, title="¡Califica tu experiencia!",
                                     description=panel.feedback_message or "¿Cómo calificarías el soporte que recibiste?")
            feedback.set_footer(text=f"Ticket #{num}")
            await self._dm(ticket.user_id, feedback, view=feedback_view(ticket.id))
        return closed_embed

    async def _dm(self, user_id: str, embed: discord.Embed, file: discord.File | None = None,
                  view: discord.ui.View | None = None) -> bool:
        try:
            user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
            kwargs: dict[str, Any] = {"embed": embed}
            if file is not None:
                kwargs["file"] = file
            if view is not None:
                kwargs["view"] = view
            await user.send(**kwargs)
            return True
        except (discord.HTTPException, ValueError):
            return False

    async def close_by_system(self, channel_id: str, closed_by: str, reason: str) -> bool:
        """Close without an interaction (shop admin flows) using the normal close pipeline."""
        found = await self.by_channel(int(channel_id))
        if found is None or found[0].status != "open":
            return False
        ticket, panel = found
        guild = self.bot.get_guild(int(ticket.guild_id))
        channel = guild.get_channel(int(channel_id)) if guild else None
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"Ticket channel {channel_id} is not available")
        embed = await self.close(channel, ticket, panel, closed_by, reason)
        await channel.send(embed=embed, view=closed_actions())
        return True

    # ── Reopen / claim / delete ──────────────────────────────────────────

    async def reopen(self, channel: discord.TextChannel, ticket: Ticket, panel: TicketPanel | None,
                     by: discord.abc.User) -> discord.Embed:
        await self.update(ticket.id, status="open", closed_at=None, closed_by=None, close_reason=None,
                          last_activity_at=utcnow())
        try:
            await channel.set_permissions(discord.Object(int(ticket.user_id)), overwrite=_ALLOW_STAFF)
            for uid in ticket.added_users or []:
                await channel.set_permissions(discord.Object(int(uid)), overwrite=discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True))
        except discord.HTTPException:
            pass
        pattern = (panel.naming_pattern if panel else None) or "ticket-{number}"
        name = (pattern.replace("{number}", pad(ticket.number), 1).replace("{username}", "user", 1)
                .replace("{userid}", ticket.user_id, 1))[:100]
        try:
            await channel.edit(name=name)
            if panel and panel.category_id and panel.category_id.isdigit():
                category = channel.guild.get_channel(int(panel.category_id))
                if isinstance(category, discord.CategoryChannel):
                    await channel.edit(category=category, sync_permissions=False)
        except discord.HTTPException:
            pass
        log_embed = discord.Embed(color=OK, title="Ticket reabierto", timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Ticket", value=f"#{pad(ticket.number)}", inline=True)
        log_embed.add_field(name="Reabierto por", value=by.mention, inline=True)
        await self.log(channel.guild, panel, log_embed)
        return discord.Embed(color=OK, title="Ticket reabierto", timestamp=discord.utils.utcnow(),
                             description=f"Este ticket fue reabierto por {by.mention}.")

    async def claim(self, channel: discord.TextChannel, ticket: Ticket, panel: TicketPanel | None,
                    member: discord.Member) -> None:
        await self.update(ticket.id, claimed_by=str(member.id))
        if panel is not None and panel.claim_lock_others:
            for rid in panel.staff_role_ids or []:
                role = channel.guild.get_role(int(rid)) if rid.isdigit() else None
                if role is not None:
                    try:
                        await channel.set_permissions(role, send_messages=False)
                    except discord.HTTPException:
                        pass
            try:
                await channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
            except discord.HTTPException:
                pass
        log_embed = discord.Embed(color=TRANSCRIPT_BLUE, title="Ticket reclamado", timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Ticket", value=f"#{pad(ticket.number)}", inline=True)
        log_embed.add_field(name="Reclamado por", value=member.mention, inline=True)
        await self.log(channel.guild, panel, log_embed)

    async def delete(self, interaction: discord.Interaction) -> None:
        guild, channel = interaction.guild, interaction.channel
        member = interaction.user
        if guild is None or not isinstance(channel, discord.TextChannel) or not isinstance(member, discord.Member):
            return
        found = await self.by_channel(channel.id)
        if found is None:
            await interaction.response.send_message("Este no es un canal de ticket.", ephemeral=True)
            return
        ticket, panel = found
        staff_roles = set(panel.staff_role_ids or []) | set(panel.admin_role_ids or []) if panel else set()
        if not ({str(r.id) for r in member.roles} & staff_roles or member.guild_permissions.manage_channels):
            await interaction.response.send_message("Solo el staff puede eliminar tickets.", ephemeral=True)
            return
        await interaction.response.send_message("Este ticket se eliminara en 5 segundos...")

        config = await self.bot.configs.get(guild.id)
        is_rank_ticket = bool(panel and "rang" in (panel.name or "").lower())
        images_channel = text_channel(guild, config.dar_rango_images_channel_id or config.verification_log_channel_id)
        if is_rank_ticket and isinstance(images_channel, discord.TextChannel):
            try:
                await archive_rank_images(channel, images_channel, ticket.user_id, ticket_number=ticket.number)
            except discord.HTTPException:
                log.exception("Failed to archive rank ticket images before delete")

        log_embed = discord.Embed(color=ERROR, title="Ticket eliminado", timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Ticket", value=f"#{pad(ticket.number)}", inline=True)
        log_embed.add_field(name="Eliminado por", value=member.mention, inline=True)
        log_embed.add_field(name="Creador", value=f"<@{ticket.user_id}>", inline=True)
        await self.log(guild, panel, log_embed)

        await asyncio.sleep(5)
        try:
            await channel.delete(reason="Ticket eliminado")
            await self.update(ticket.id, status="deleted")
        except discord.HTTPException:
            log.exception("Failed to delete ticket channel #%s", ticket.number)
            try:
                await interaction.followup.send(
                    "No pude eliminar el canal del ticket. Revisa mis permisos e intenta otra vez.", ephemeral=True)
            except discord.HTTPException:
                pass

    # ── Stats (Ticket King-style) ────────────────────────────────────────

    async def stats(self, guild_id: int) -> dict[str, Any]:
        gid = str(guild_id)
        week_ago = utcnow() - timedelta(days=7)
        async with self.bot.db.session() as session:
            def count(*conds: Any) -> Any:
                return session.scalar(select(func.count()).select_from(Ticket).where(Ticket.guild_id == gid, *conds))

            open_, closed, total, this_week = (
                await count(Ticket.status == "open"), await count(Ticket.status == "closed"),
                await count(), await count(Ticket.created_at >= week_ago))
            avg_rating = await session.scalar(select(func.avg(Ticket.rating)).where(
                Ticket.guild_id == gid, Ticket.rating.is_not(None)))
            avg_first_response = await session.scalar(select(
                func.avg(func.extract("epoch", Ticket.first_response - Ticket.created_at))
            ).where(Ticket.guild_id == gid, Ticket.first_response.is_not(None)))
            top_claimers = (await session.execute(
                select(Ticket.claimed_by, func.count().label("n")).where(
                    Ticket.guild_id == gid, Ticket.claimed_by.is_not(None))
                .group_by(Ticket.claimed_by).order_by(func.count().desc()).limit(5))).all()
            by_priority = dict((await session.execute(
                select(Ticket.priority, func.count()).where(Ticket.guild_id == gid, Ticket.status == "open")
                .group_by(Ticket.priority))).all())
        return {
            "open": open_ or 0, "closed": closed or 0, "total": total or 0, "thisWeek": this_week or 0,
            "avgRating": round(float(avg_rating), 1) if avg_rating is not None else None,
            "avgFirstResponseSeconds": int(avg_first_response) if avg_first_response is not None else None,
            "topClaimers": [(uid, n) for uid, n in top_claimers], "openByPriority": by_priority,
        }


# ─── Rank-ticket image archive ───────────────────────────────────────────────

MAX_ARCHIVE_IMAGE_BYTES = 10 * 1024 * 1024
ARCHIVE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


async def _collect_image_urls(channel: discord.TextChannel) -> list[str]:
    urls: list[str] = []
    async for message in channel.history(limit=1000, oldest_first=True):
        for att in message.attachments:
            if (att.content_type or "").startswith("image/") or re.search(r"\.(png|jpe?g|gif|webp)$", att.filename, re.I):
                urls.append(att.url)
    return urls


async def _download(http: aiohttp.ClientSession, url: str, index: int) -> discord.File | None:
    try:
        async with http.get(url) as resp:
            content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            if resp.status != 200 or content_type not in ARCHIVE_TYPES:
                return None
            data = await resp.content.read(MAX_ARCHIVE_IMAGE_BYTES + 1)
            if len(data) > MAX_ARCHIVE_IMAGE_BYTES:
                return None
            return discord.File(io.BytesIO(data), filename=f"rango-{index + 1}.{ARCHIVE_TYPES[content_type]}")
    except (aiohttp.ClientError, TimeoutError):
        return None


async def archive_rank_images(
    channel: discord.TextChannel, log_channel: discord.TextChannel, user_id: str, *,
    ticket_number: int | None = None, role_name: str | None = None, color: int = OK, assigned_by: str | None = None,
) -> int:
    """Re-upload a ticket's images to an archive channel (Discord URLs break once the channel is deleted)."""
    urls = await _collect_image_urls(channel)
    label = f"#{pad(ticket_number)}" if ticket_number else channel.name
    header = discord.Embed(color=color, title="Registro de rango", description=f"ID: `{user_id}` | Ticket {label}",
                           timestamp=discord.utils.utcnow())
    header.add_field(name="Usuario", value=f"<@{user_id}>", inline=True)
    header.add_field(name="Canal", value=channel.mention, inline=True)
    header.add_field(name="Imagenes", value=str(len(urls)), inline=True)
    if role_name:
        header.add_field(name="Rango", value=role_name, inline=True)
    if assigned_by:
        header.add_field(name="Asignado por", value=assigned_by, inline=True)
    await log_channel.send(content=f"ID: `{user_id}` | <@{user_id}> | Ticket {label}"
                                   f"{f' | {role_name}' if role_name else ''}", embed=header)
    if not urls:
        await log_channel.send("_(sin imagenes adjuntas en el canal)_")
        return 0
    uploaded = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as http:
        for start in range(0, len(urls), 10):
            files = [f for f in await asyncio.gather(
                *(_download(http, u, start + i) for i, u in enumerate(urls[start:start + 10]))) if f]
            if files:
                await log_channel.send(files=files)
                uploaded += len(files)
    if uploaded < len(urls):
        log.warning("Archived %d/%d rank ticket images for %s", uploaded, len(urls), channel.id)
    return uploaded
