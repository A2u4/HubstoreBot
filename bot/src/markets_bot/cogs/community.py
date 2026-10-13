"""Community features: suggestions, starboard, AFK and reminders."""

from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from markets_bot.bot import MarketsBot
from markets_bot.core.cache import TtlCache
from markets_bot.core.pipeline import MessagePipeline
from markets_bot.core.tasks import resilient
from markets_bot.core.utils import ERROR, INFO, OK, aware, discord_ts, module_color, parse_duration, utcnow
from markets_bot.db.models import AfkStatus, GuildConfig, Reminder, StarboardEntry, Suggestion

log = logging.getLogger(__name__)

SUGGESTION_STATUS = {"aprobar": "approved", "rechazar": "denied", "implementar": "implemented"}
STATUS_LABEL = {"approved": "✅ Aprobada", "denied": "❌ Rechazada", "implemented": "🚀 Implementada"}
STATUS_COLOR = {"approved": OK, "denied": ERROR, "implemented": INFO}
STATUS_WORD = {"approved": "aprobada", "denied": "rechazada", "implemented": "implementada"}
STATUS_EMOJI = {"pending": "⏳", "approved": "✅", "denied": "❌", "implemented": "🚀"}


def star_tier(count: int) -> str:
    return "🌟" if count >= 10 else "⭐" if count >= 5 else "✨"


class Community(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self._afk: TtlCache[dict[str, AfkStatus]] = TtlCache(300, 2_000)
        bot.router.prefix("button", "suggest_up_", self.on_suggestion_vote)
        bot.router.prefix("button", "suggest_down_", self.on_suggestion_vote)
        bot.pipeline.register("afk", self.afk_messages, MessagePipeline.AFK)

    async def cog_load(self) -> None:
        self.deliver_reminders.start()

    async def cog_unload(self) -> None:
        self.deliver_reminders.cancel()

    # ── Suggestions ──────────────────────────────────────────────────────

    async def on_suggestion_vote(self, interaction: discord.Interaction) -> None:
        custom_id = str((interaction.data or {}).get("custom_id", ""))
        upvote = custom_id.startswith("suggest_up_")
        suggestion_id = custom_id.removeprefix("suggest_up_").removeprefix("suggest_down_")
        user_id = str(interaction.user.id)
        async with self.bot.db.session() as session:
            suggestion = await session.get(Suggestion, suggestion_id, with_for_update=True)
            if suggestion is None:
                await interaction.response.send_message("Sugerencia no encontrada.", ephemeral=True)
                return
            ups, downs = list(suggestion.upvotes or []), list(suggestion.downvotes or [])
            mine, other = (ups, downs) if upvote else (downs, ups)
            if user_id in mine:
                mine.remove(user_id)
            else:
                mine.append(user_id)
                if user_id in other:
                    other.remove(user_id)
            suggestion.upvotes, suggestion.downvotes = ups, downs
        message = interaction.message
        if message and message.embeds:
            embed = message.embeds[0]
            for index, embed_field in enumerate(embed.fields):
                if embed_field.name == "Votos":
                    embed.set_field_at(index, name="Votos", value=f"👍 {len(ups)} | 👎 {len(downs)}", inline=embed_field.inline)
            try:
                await message.edit(embed=embed)
            except discord.HTTPException:
                pass
        await interaction.response.send_message("👍 Voto registrado!" if upvote else "👎 Voto registrado!", ephemeral=True)

    sugerencia = app_commands.Group(name="sugerencia", description="Sistema de sugerencias", guild_only=True,
                                    extras={"module": "suggestions", "cooldown": 10})

    @sugerencia.command(name="crear", description="Enviar una nueva sugerencia")
    @app_commands.describe(contenido="Tu sugerencia")
    async def suggest(self, interaction: discord.Interaction, contenido: str) -> None:
        guild = interaction.guild
        assert guild is not None
        config = await self.bot.configs.get(guild.id)
        channel_id = config.suggestions_channel_id or str(interaction.channel_id)
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message(
                "Canal de sugerencias no configurado. Pide a un admin que lo configure con `/config`.", ephemeral=True)
            return
        suggestion = Suggestion(guild_id=str(guild.id), channel_id=channel_id, user_id=str(interaction.user.id),
                                content=contenido)
        async with self.bot.db.session() as session:
            session.add(suggestion)
        embed = discord.Embed(color=module_color("suggestions"), title="Nueva Sugerencia", description=contenido,
                              timestamp=discord.utils.utcnow())
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Estado", value="⏳ Pendiente", inline=True)
        embed.add_field(name="Votos", value="👍 0 | 👎 0", inline=True)
        embed.set_footer(text=f"ID: {suggestion.id[:8]}")
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(custom_id=f"suggest_up_{suggestion.id}", label="👍 A favor",
                                        style=discord.ButtonStyle.success))
        view.add_item(discord.ui.Button(custom_id=f"suggest_down_{suggestion.id}", label="👎 En contra",
                                        style=discord.ButtonStyle.danger))
        message = await channel.send(embed=embed, view=view)
        async with self.bot.db.session() as session:
            await session.execute(update(Suggestion).where(Suggestion.id == suggestion.id).values(message_id=str(message.id)))
        await interaction.response.send_message(
            "¡Sugerencia enviada!" if channel_id == str(interaction.channel_id)
            else f"¡Tu sugerencia ha sido enviada en <#{channel_id}>!", ephemeral=True)

    async def _review(self, interaction: discord.Interaction, action: str, suggestion_id: str, note: str | None) -> None:
        if not interaction.permissions.manage_guild:
            await interaction.response.send_message("Necesitas el permiso **Gestionar Servidor**.", ephemeral=True)
            return
        status = SUGGESTION_STATUS[action]
        async with self.bot.db.session() as session:
            suggestion = (await session.execute(select(Suggestion).where(
                Suggestion.guild_id == str(interaction.guild_id), Suggestion.id.startswith(suggestion_id)).limit(1)
            )).scalar_one_or_none()
            if suggestion is None:
                await interaction.response.send_message("Sugerencia no encontrada.", ephemeral=True)
                return
            suggestion.status = status
            if note:
                suggestion.staff_note = note
            suggestion.reviewed_by = str(interaction.user.id)
        channel = self.bot.get_channel(int(suggestion.channel_id))
        if isinstance(channel, discord.abc.Messageable) and suggestion.message_id:
            try:
                message = await channel.fetch_message(int(suggestion.message_id))
                embed = message.embeds[0] if message.embeds else discord.Embed()
                embed.color = STATUS_COLOR[status]
                embed.clear_fields()
                embed.add_field(name="Estado", value=STATUS_LABEL[status], inline=True)
                embed.add_field(name="Votos", value=f"👍 {len(suggestion.upvotes or [])} | 👎 {len(suggestion.downvotes or [])}",
                                inline=True)
                if note:
                    embed.add_field(name="Nota del Staff", value=note, inline=False)
                await message.edit(embed=embed)
            except discord.HTTPException:
                pass
        log_channel = self.bot.get_channel(int((await self.bot.configs.get(interaction.guild_id or 0)).suggestions_log_channel_id or 0))
        if isinstance(log_channel, discord.abc.Messageable):
            log_embed = discord.Embed(color=STATUS_COLOR[status], title=f"Sugerencia {STATUS_WORD[status]}",
                                      description=suggestion.content[:4000], timestamp=discord.utils.utcnow())
            log_embed.add_field(name="Autor", value=f"<@{suggestion.user_id}>", inline=True)
            log_embed.add_field(name="Revisada por", value=interaction.user.mention, inline=True)
            if note:
                log_embed.add_field(name="Nota", value=note[:1024], inline=False)
            try:
                await log_channel.send(embed=log_embed)
            except discord.HTTPException:
                pass
        await interaction.response.send_message(
            f"La sugerencia `{suggestion.id[:8]}` ha sido **{STATUS_WORD[status]}**.", ephemeral=True)

    @sugerencia.command(name="aprobar", description="Aprobar una sugerencia (solo mods)")
    @app_commands.describe(id="ID de la sugerencia", nota="Nota del staff")
    async def approve(self, interaction: discord.Interaction, id: str, nota: str | None = None) -> None:
        await self._review(interaction, "aprobar", id, nota)

    @sugerencia.command(name="rechazar", description="Rechazar una sugerencia (solo mods)")
    @app_commands.describe(id="ID de la sugerencia", nota="Razón del rechazo")
    async def deny(self, interaction: discord.Interaction, id: str, nota: str | None = None) -> None:
        await self._review(interaction, "rechazar", id, nota)

    @sugerencia.command(name="implementar", description="Marcar una sugerencia como implementada (solo mods)")
    @app_commands.describe(id="ID de la sugerencia", nota="Notas de implementación")
    async def implement(self, interaction: discord.Interaction, id: str, nota: str | None = None) -> None:
        await self._review(interaction, "implementar", id, nota)

    @sugerencia.command(name="lista", description="Listar sugerencias recientes")
    async def list_suggestions(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(Suggestion).where(Suggestion.guild_id == str(interaction.guild_id))
                                          .order_by(Suggestion.created_at.desc()).limit(10))).scalars().all()
        if not rows:
            await interaction.response.send_message("Aún no hay sugerencias.", ephemeral=True)
            return
        lines = [f"{STATUS_EMOJI.get(s.status, '❓')} `{s.id[:8]}` {s.content[:60]}{'...' if len(s.content) > 60 else ''} "
                 f"(👍{len(s.upvotes or [])} 👎{len(s.downvotes or [])})" for s in rows]
        await interaction.response.send_message(embed=discord.Embed(
            color=module_color("suggestions"), title="Sugerencias Recientes", description="\n".join(lines),
            timestamp=discord.utils.utcnow()))

    # ── Starboard ────────────────────────────────────────────────────────

    async def _starboard(self, payload: discord.RawReactionActionEvent, added: bool) -> None:
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        config = await self.bot.configs.get(payload.guild_id)
        if guild is None or not config.starboard_enabled or not config.starboard_channel_id:
            return
        if (payload.emoji.name or str(payload.emoji)) != (config.starboard_emoji or "⭐"):
            return
        if str(payload.channel_id) == config.starboard_channel_id:
            return
        board = guild.get_channel(int(config.starboard_channel_id))
        source = guild.get_channel_or_thread(payload.channel_id)
        if not isinstance(board, discord.TextChannel) or not isinstance(source, discord.abc.Messageable):
            return
        try:
            message = await source.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        if added and message.author.id == payload.user_id:
            return  # no self-starring
        reaction = next((r for r in message.reactions if (getattr(r.emoji, "name", None) or str(r.emoji))
                         == (config.starboard_emoji or "⭐")), None)
        count = reaction.count if reaction else 0
        threshold = config.starboard_threshold or 3
        async with self.bot.db.session() as session:
            entry = (await session.execute(select(StarboardEntry).where(
                StarboardEntry.guild_id == str(guild.id), StarboardEntry.original_msg_id == str(message.id)
            ))).scalar_one_or_none()

        tier = star_tier(count)
        jump = message.jump_url
        embed = discord.Embed(color=0xFEE75C, timestamp=message.created_at,
                              description=f"{message.content}\n\n[Ir al mensaje]({jump})" if message.content
                              else f"[Ir al mensaje]({jump})")
        embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="Canal", value=f"<#{message.channel.id}>", inline=True)
        embed.set_footer(text=f"{tier} {count}")
        attachment = message.attachments[0].url if message.attachments else None
        image = attachment or next(((e.image.url or e.thumbnail.url) for e in message.embeds
                                    if e.image.url or e.thumbnail.url), None)
        if image:
            embed.set_image(url=image)
        content = f"{tier} **{count}** | <#{message.channel.id}>"

        if count >= threshold:
            board_message_id = entry.starboard_msg_id if entry else None
            posted = None
            if board_message_id:
                try:
                    posted = await board.fetch_message(int(board_message_id))
                    await posted.edit(content=content, embed=embed)
                except discord.HTTPException:
                    posted = None
            if posted is None:
                posted = await board.send(content=content, embed=embed)
            async with self.bot.db.session() as session:
                await session.execute(insert(StarboardEntry).values(
                    guild_id=str(guild.id), original_msg_id=str(message.id), original_ch_id=str(message.channel.id),
                    starboard_msg_id=str(posted.id), author_id=str(message.author.id), stars=count,
                    content=message.content[:2000] or None, attachment_url=attachment,
                ).on_conflict_do_update(index_elements=["guildId", "originalMsgId"],
                                        set_={"starboardMsgId": str(posted.id), "stars": count}))
        elif entry is not None:
            if entry.starboard_msg_id:
                try:
                    await board.get_partial_message(int(entry.starboard_msg_id)).delete()
                except discord.HTTPException:
                    pass
            async with self.bot.db.session() as session:
                if count == 0:
                    await session.execute(delete(StarboardEntry).where(StarboardEntry.id == entry.id))
                else:
                    await session.execute(update(StarboardEntry).where(StarboardEntry.id == entry.id).values(
                        stars=count, starboard_msg_id=None))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.member is not None and payload.member.bot:
            return
        try:
            await self._starboard(payload, True)
        except discord.HTTPException:
            log.exception("Starboard reaction add failed")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        try:
            await self._starboard(payload, False)
        except discord.HTTPException:
            log.exception("Starboard reaction remove failed")

    # ── AFK ──────────────────────────────────────────────────────────────

    async def _afk_map(self, guild_id: int) -> dict[str, AfkStatus]:
        key = str(guild_id)
        cached = self._afk.get(key)
        if cached is not None:
            return cached
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(AfkStatus).where(AfkStatus.guild_id == key))).scalars().all()
        result = {r.user_id: r for r in rows}
        self._afk.set(key, result)
        return result

    async def afk_messages(self, message: discord.Message, config: GuildConfig) -> None:
        """Clear the AFK status of whoever talks, and announce mentioned AFK users."""
        if message.guild is None:
            return
        statuses = await self._afk_map(message.guild.id)
        if not statuses:
            return
        mine = statuses.get(str(message.author.id))
        if mine is not None:
            async with self.bot.db.session() as session:
                await session.execute(delete(AfkStatus).where(AfkStatus.id == mine.id))
            statuses.pop(str(message.author.id), None)
            minutes = int((utcnow() - mine.created_at).total_seconds() // 60)
            elapsed = f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"
            try:
                await message.reply(f"¡Bienvenido de vuelta! Estuviste AFK por **{elapsed}**.", delete_after=5)
            except discord.HTTPException:
                pass
        mentioned = [statuses[str(u.id)] for u in message.mentions if str(u.id) in statuses]
        if mentioned:
            lines = [f"<@{a.user_id}> está AFK: **{a.reason}** (desde {discord_ts(a.created_at)})" for a in mentioned]
            try:
                await message.reply("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    afk = app_commands.Group(name="afk", description="Establecer o quitar tu estado AFK", guild_only=True,
                             extras={"module": "afk", "cooldown": 5})

    @afk.command(name="establecer", description="Ponerte como AFK")
    @app_commands.describe(razon="Razón del AFK")
    async def afk_set(self, interaction: discord.Interaction, razon: str = "AFK") -> None:
        guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
        async with self.bot.db.session() as session:
            await session.execute(insert(AfkStatus).values(guild_id=guild_id, user_id=user_id, reason=razon)
                                  .on_conflict_do_update(index_elements=["guildId", "userId"],
                                                         set_={"reason": razon, "createdAt": utcnow()}))
        self._afk.delete(guild_id)
        await interaction.response.send_message(embed=discord.Embed(
            color=module_color("afk"), description=f"{interaction.user.mention} ahora está AFK: **{razon}**",
            timestamp=discord.utils.utcnow()))

    @afk.command(name="quitar", description="Quitar tu estado AFK")
    async def afk_clear(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        async with self.bot.db.session() as session:
            result = await session.execute(delete(AfkStatus).where(
                AfkStatus.guild_id == guild_id, AfkStatus.user_id == str(interaction.user.id)))
        self._afk.delete(guild_id)
        await interaction.response.send_message(
            "¡Bienvenido de vuelta! Tu estado AFK ha sido eliminado." if result.rowcount else "No estás AFK.",
            ephemeral=True)

    # ── Reminders ────────────────────────────────────────────────────────

    @tasks.loop(seconds=15)
    @resilient
    async def deliver_reminders(self) -> None:
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        async with self.bot.db.session() as session:
            due = (await session.execute(select(Reminder).where(
                Reminder.guild_id.in_(guild_ids), Reminder.fired.is_(False), Reminder.remind_at <= utcnow()
            ).limit(20))).scalars().all()
            for reminder in due:
                reminder.fired = True  # marked even if sending fails, to avoid retry loops
        for reminder in due:
            channel = self.bot.get_channel(int(reminder.channel_id))
            if not isinstance(channel, discord.abc.Messageable):
                continue
            embed = discord.Embed(color=module_color("utility"), title="Recordatorio", description=reminder.message,
                                  timestamp=aware(reminder.created_at))
            embed.set_footer(text="Programado")
            try:
                await channel.send(content=f"<@{reminder.user_id}>", embed=embed,
                                   allowed_mentions=discord.AllowedMentions(users=[discord.Object(int(reminder.user_id))]))
            except discord.HTTPException as exc:
                log.error("Failed to deliver reminder %s: %s", reminder.id, exc)

    @deliver_reminders.before_loop
    async def _wait(self) -> None:
        await self.bot.wait_until_ready()

    recordatorio = app_commands.Group(name="recordatorio", description="Gestionar recordatorios personales",
                                      guild_only=True, extras={"module": "utility", "cooldown": 3})

    @recordatorio.command(name="crear", description="Crear un nuevo recordatorio")
    @app_commands.describe(tiempo="Cuándo recordar (ej. 10m, 2h, 1d)", mensaje="De qué recordarte")
    async def remind(self, interaction: discord.Interaction, tiempo: str, mensaje: str) -> None:
        seconds = parse_duration(tiempo)
        if not seconds or seconds < 10:
            await interaction.response.send_message(
                "Duración inválida. El mínimo es 10 segundos. Usa formatos como `10m`, `2h`, `1d`.", ephemeral=True)
            return
        if seconds > 30 * 86400:
            await interaction.response.send_message("La duración máxima del recordatorio es de 30 días.", ephemeral=True)
            return
        remind_at = utcnow() + timedelta(seconds=seconds)
        reminder = Reminder(guild_id=str(interaction.guild_id), user_id=str(interaction.user.id),
                            channel_id=str(interaction.channel_id), message=mensaje, remind_at=remind_at)
        async with self.bot.db.session() as session:
            session.add(reminder)
        embed = discord.Embed(color=module_color("utility"), timestamp=discord.utils.utcnow(),
                              description=f"¡Recordatorio creado! Te recordaré {discord_ts(remind_at)}.\n**Mensaje:** {mensaje}")
        embed.set_footer(text=f"ID: {reminder.id[:8]}")
        await interaction.response.send_message(embed=embed)

    @recordatorio.command(name="lista", description="Ver tus recordatorios activos")
    async def reminders(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(Reminder).where(
                Reminder.user_id == str(interaction.user.id), Reminder.guild_id == str(interaction.guild_id),
                Reminder.fired.is_(False), Reminder.remind_at > utcnow()).order_by(Reminder.remind_at).limit(10)
            )).scalars().all()
        if not rows:
            await interaction.response.send_message("No tienes recordatorios activos.", ephemeral=True)
            return
        lines = [f"**{i}.** {r.message[:80]} — {discord_ts(r.remind_at)}\n`ID: {r.id[:8]}`" for i, r in enumerate(rows, 1)]
        embed = discord.Embed(color=module_color("utility"), title="Tus Recordatorios", description="\n\n".join(lines),
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"{len(rows)} recordatorio(s) activo(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @recordatorio.command(name="eliminar", description="Eliminar un recordatorio")
    @app_commands.describe(id="ID del recordatorio (usa /recordatorio lista para encontrarlo)")
    async def remove_reminder(self, interaction: discord.Interaction, id: str) -> None:
        async with self.bot.db.session() as session:
            reminder = (await session.execute(select(Reminder).where(
                Reminder.user_id == str(interaction.user.id), Reminder.guild_id == str(interaction.guild_id),
                Reminder.fired.is_(False), Reminder.id.startswith(id)).limit(1))).scalar_one_or_none()
            if reminder is None:
                await interaction.response.send_message(
                    "Recordatorio no encontrado. Usa `/recordatorio lista` para ver tus recordatorios activos.",
                    ephemeral=True)
                return
            await session.delete(reminder)
        await interaction.response.send_message(f"Recordatorio eliminado: **{reminder.message[:80]}**", ephemeral=True)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Community(bot))
