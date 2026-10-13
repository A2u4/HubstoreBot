"""Giveaways (``/sorteo``): button entries, timed draws and rerolls."""

from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select, update

from markets_bot.bot import MarketsBot
from markets_bot.core.tasks import resilient
from markets_bot.core.utils import aware, crypto_sample, discord_ts, module_color, parse_duration, utcnow
from markets_bot.db.models import Giveaway

log = logging.getLogger(__name__)

ENDED_COLOR = 0x99AAB5
MENTION_CHOICES = [app_commands.Choice(name="@everyone", value="@everyone"),
                   app_commands.Choice(name="@here", value="@here"),
                   app_commands.Choice(name="Ninguno", value="none")]


def entry_view(count: int, *, first: bool = False) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(custom_id="giveaway_enter", style=discord.ButtonStyle.success,
                                    label="🎉 Participar" if first else "🎉 Participar en sorteo"))
    view.add_item(discord.ui.Button(custom_id="giveaway_count", style=discord.ButtonStyle.secondary, disabled=True,
                                    label=f"{count} participantes" if first else f"{count} participaciones"))
    return view


class Giveaways(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        bot.router.exact("button", "giveaway_enter", self.on_enter)

    async def cog_load(self) -> None:
        self.end_expired.start()

    async def cog_unload(self) -> None:
        self.end_expired.cancel()

    async def on_enter(self, interaction: discord.Interaction) -> None:
        if interaction.message is None:
            return
        user_id = str(interaction.user.id)
        async with self.bot.db.session() as session:
            giveaway = (await session.execute(select(Giveaway).where(
                Giveaway.message_id == str(interaction.message.id), Giveaway.ended.is_(False)
            ).with_for_update())).scalar_one_or_none()
            if giveaway is None:
                await interaction.response.send_message("Este sorteo ya termino.", ephemeral=True)
                return
            entries = list(giveaway.entries or [])
            left = user_id in entries
            entries = [e for e in entries if e != user_id] if left else [*entries, user_id]
            giveaway.entries = entries
        await interaction.response.send_message(
            "Has salido del sorteo." if left else "🎉 Te has unido al sorteo! Buena suerte!", ephemeral=True)
        try:
            await interaction.message.edit(view=entry_view(len(entries)))
        except discord.HTTPException:
            pass

    async def _finish(self, giveaway: Giveaway, winners: list[str], *, from_timer: bool) -> None:
        guild = self.bot.get_guild(int(giveaway.guild_id))
        channel = guild.get_channel(int(giveaway.channel_id)) if guild else None
        if not isinstance(channel, discord.abc.Messageable) or not giveaway.message_id:
            return
        winners_text = ", ".join(f"<@{w}>" for w in winners) if winners else (
            "No hay participaciones validas." if from_timer else "No hay participantes válidos.")
        description = (f"**{giveaway.prize}**\n\n**Ganador(es):** {winners_text}\n"
                       f"**Organizado por:** <@{giveaway.host_id}>")
        if from_timer:
            description += f"\n**Participaciones:** {len(giveaway.entries or [])}"
        embed = discord.Embed(color=ENDED_COLOR, title="🎉 SORTEO FINALIZADO 🎉", description=description,
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text="Finalizado")
        try:
            message = await channel.fetch_message(int(giveaway.message_id))
            await message.edit(embed=embed, view=None)
            if winners:
                await channel.send(f"🎉 Felicidades {winners_text}! Ganaste **{giveaway.prize}**!")
            elif from_timer:
                await channel.send(f"El sorteo de **{giveaway.prize}** termino sin participaciones.")
        except discord.HTTPException:
            pass  # message deleted

    @tasks.loop(seconds=15)
    @resilient
    async def end_expired(self) -> None:
        guild_ids = [str(g.id) for g in self.bot.guilds]
        if not guild_ids:
            return
        async with self.bot.db.session() as session:
            expired = (await session.execute(select(Giveaway).where(
                Giveaway.guild_id.in_(guild_ids), Giveaway.ended.is_(False), Giveaway.ends_at <= utcnow()
            ))).scalars().all()
        for giveaway in expired:
            winners = crypto_sample(list(giveaway.entries or []), giveaway.winners)
            async with self.bot.db.session() as session:
                result = await session.execute(update(Giveaway).where(
                    Giveaway.id == giveaway.id, Giveaway.ended.is_(False)).values(ended=True, winner_ids=winners))
            if result.rowcount:
                await self._finish(giveaway, winners, from_timer=True)
                log.info("Ended giveaway %s — %s", giveaway.id, giveaway.prize)

    @end_expired.before_loop
    async def _wait(self) -> None:
        await self.bot.wait_until_ready()

    sorteo = app_commands.Group(name="sorteo", description="Sistema de sorteos", guild_only=True,
                                extras={"module": "giveaway", "cooldown": 5, "permissions": ["manage_guild"]})

    @sorteo.command(name="iniciar", description="Iniciar un nuevo sorteo")
    @app_commands.describe(premio="¿Qué vas a sortear?", duracion="Duración (ej. 1h, 1d, 7d)",
                           ganadores="Número de ganadores (por defecto: 1)", descripcion="Descripción adicional",
                           canal="Canal donde publicar (por defecto: actual)", mencionar="Mencionar antes del sorteo")
    @app_commands.choices(mencionar=MENTION_CHOICES)
    async def start(self, interaction: discord.Interaction, premio: str, duracion: str,
                    ganadores: app_commands.Range[int, 1, 20] = 1, descripcion: str | None = None,
                    canal: discord.TextChannel | None = None, mencionar: str = "none") -> None:
        channel = canal or interaction.channel
        seconds = parse_duration(duracion)
        if not seconds:
            await interaction.response.send_message("Duración inválida. Usa formatos como `1h`, `1d`, `7d`.", ephemeral=True)
            return
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("Canal inválido.", ephemeral=True)
            return
        ends_at = utcnow() + timedelta(seconds=seconds)
        embed = discord.Embed(color=module_color("giveaway"), title="🎉 SORTEO 🎉", timestamp=aware(ends_at),
                              description=f"**{premio}**\n\n{f'{descripcion}{chr(10) * 2}' if descripcion else ''}"
                                          f"¡Haz clic en el botón para participar!\n\n**Ganadores:** {ganadores}\n"
                                          f"**Termina:** {discord_ts(ends_at)} ({discord_ts(ends_at, 'F')})\n"
                                          f"**Organizado por:** {interaction.user.mention}")
        embed.set_footer(text=f"{ganadores} ganador(es)")
        mention = mencionar if mencionar != "none" else None
        message = await channel.send(content=mention, embed=embed, view=entry_view(0, first=True),
                                     allowed_mentions=discord.AllowedMentions(everyone=bool(mention)))
        async with self.bot.db.session() as session:
            session.add(Giveaway(guild_id=str(interaction.guild_id), channel_id=str(message.channel.id),
                                 message_id=str(message.id), host_id=str(interaction.user.id), prize=premio,
                                 description=descripcion, winners=ganadores, ends_at=ends_at))
        here = message.channel.id == interaction.channel_id
        await interaction.response.send_message("¡Sorteo iniciado!" if here else f"¡Sorteo iniciado en {message.channel.mention}!",
                                                ephemeral=True)

    @sorteo.command(name="finalizar", description="Finalizar un sorteo antes de tiempo")
    @app_commands.describe(id="ID del mensaje del sorteo")
    async def end(self, interaction: discord.Interaction, id: str) -> None:
        async with self.bot.db.session() as session:
            giveaway = (await session.execute(select(Giveaway).where(
                Giveaway.guild_id == str(interaction.guild_id), Giveaway.message_id == id, Giveaway.ended.is_(False)
            ))).scalar_one_or_none()
            if giveaway is None:
                await interaction.response.send_message("Sorteo no encontrado o ya finalizado.", ephemeral=True)
                return
            winners = crypto_sample(list(giveaway.entries or []), giveaway.winners)
            giveaway.ended = True
            giveaway.winner_ids = winners
        await interaction.response.send_message("¡Sorteo finalizado!", ephemeral=True)
        await self._finish(giveaway, winners, from_timer=False)

    @sorteo.command(name="resortear", description="Elegir nuevos ganadores de un sorteo finalizado")
    @app_commands.describe(id="ID del mensaje del sorteo", ganadores="Número de nuevos ganadores")
    async def reroll(self, interaction: discord.Interaction, id: str, ganadores: app_commands.Range[int, 1] = 1) -> None:
        async with self.bot.db.session() as session:
            giveaway = (await session.execute(select(Giveaway).where(
                Giveaway.guild_id == str(interaction.guild_id), Giveaway.message_id == id, Giveaway.ended.is_(True)
            ))).scalar_one_or_none()
            if giveaway is None:
                await interaction.response.send_message("Sorteo finalizado no encontrado.", ephemeral=True)
                return
            winners = crypto_sample(list(giveaway.entries or []), ganadores)
            giveaway.winner_ids = winners
        if not winners:
            await interaction.response.send_message("No hay participantes válidos para resortear.", ephemeral=True)
            return
        text = ", ".join(f"<@{w}>" for w in winners)
        channel = self.bot.get_channel(int(giveaway.channel_id))
        if isinstance(channel, discord.abc.Messageable):
            try:
                await channel.send(f"🎉 ¡Nuevo(s) ganador(es) de **{giveaway.prize}**: {text}! ¡Felicidades!")
            except discord.HTTPException:
                pass
        await interaction.response.send_message(f"¡Resorteado! Nuevo(s) ganador(es): {text}", ephemeral=True)

    @sorteo.command(name="lista", description="Listar sorteos activos")
    async def list_(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            active = (await session.execute(select(Giveaway).where(
                Giveaway.guild_id == str(interaction.guild_id), Giveaway.ended.is_(False)
            ).order_by(Giveaway.ends_at))).scalars().all()
        if not active:
            await interaction.response.send_message("No hay sorteos activos.", ephemeral=True)
            return
        lines = [f"**{g.prize}** — {len(g.entries or [])} participantes — Termina {discord_ts(g.ends_at)} — "
                 f"[Ir](https://discord.com/channels/{interaction.guild_id}/{g.channel_id}/{g.message_id})" for g in active]
        await interaction.response.send_message(embed=discord.Embed(
            color=module_color("giveaway"), title="Sorteos Activos", description="\n\n".join(lines)[:4096],
            timestamp=discord.utils.utcnow()))


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Giveaways(bot))
