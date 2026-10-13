"""Reputation: ``/rep``, ``/reputacion``, ``/toprep`` and the ``+rep @user`` text command."""

from __future__ import annotations

import re

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from markets_bot.bot import MarketsBot
from markets_bot.core.dedupe import claim_side_effect
from markets_bot.core.pipeline import MessagePipeline
from markets_bot.core.utils import OK, discord_ts, is_snowflake, module_color
from markets_bot.db.models import GuildConfig, Reputation
from markets_bot.services.reputation import DEFAULT_MIGRATION_REASON, ReputationService
from markets_bot.web.internal_server import HttpError, json_response, read_json

MEDALS = ("🥇", "🥈", "🥉")
REP_PREFIX = "+rep"
MENTION_RE = re.compile(r"<@!?\d+>")


def rep_embed(giver: discord.abc.User, target: discord.abc.User, reason: str | None, total: int,
              prefix: str = "") -> discord.Embed:
    description = f"{prefix}{giver.mention} dio **+1 rep** a {target.mention}" if not prefix \
        else f"{prefix} **+1 rep** a {target.mention}"
    if reason:
        description += f"\nRazón: {reason}"
    embed = discord.Embed(color=module_color("reputation"), description=description, timestamp=discord.utils.utcnow())
    embed.set_footer(text=f"{target.name} ahora tiene {total} rep")
    return embed


class ReputationCog(commands.Cog, name="Reputation"):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self.service = ReputationService(bot)
        bot.pipeline.register("reputation", self.text_rep, MessagePipeline.REPUTATION)
        route = bot.internal.route
        route("POST", "/internal/reputation/leaderboard")(self._leaderboard_route)
        route("POST", "/internal/reputation/add")(self._add_route)
        route("POST", "/internal/reputation/migrate")(self._migrate_route)

    async def _give(self, interaction: discord.Interaction, target: discord.User, reason: str | None,
                    *, slash_style: bool) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("No se pudo obtener el servidor.", ephemeral=True)
            return
        if target.bot:
            await interaction.response.send_message("No puedes dar reputación a bots.", ephemeral=True)
            return
        if target.id == interaction.user.id:
            await interaction.response.send_message("No puedes darte reputación a ti mismo.", ephemeral=True)
            return
        created = await self.service.grant_once(source="interaction", source_id=interaction.id,
                                                guild_id=interaction.guild_id, user_id=target.id,
                                                giver_id=interaction.user.id, reason=reason)
        if not created:
            await interaction.response.send_message("Esta reputación ya fue procesada.", ephemeral=True)
            return
        total = await self.service.total(interaction.guild_id, target.id)
        embed = rep_embed(interaction.user, target, reason, total, prefix="" if slash_style else "✅ Diste")
        await interaction.response.send_message(embed=embed)

    async def text_rep(self, message: discord.Message, config: GuildConfig) -> None:
        """``+rep @user [razón]`` — the frictionless legacy text command."""
        if not config.reputation_enabled or not message.content.startswith(REP_PREFIX) or message.guild is None:
            return
        target = message.mentions[0] if message.mentions else None
        if target is None:
            return
        if target.id == message.author.id:
            await message.reply("No puedes darte reputación a ti mismo.")
            return
        if target.bot:
            await message.reply("No puedes dar reputación a bots.")
            return
        reason = MENTION_RE.sub("", message.content[len(REP_PREFIX):].strip(), count=1).strip() or None
        created = await self.service.grant_once(source="message", source_id=message.id, guild_id=message.guild.id,
                                                user_id=target.id, giver_id=message.author.id, reason=reason)
        if not created or not claim_side_effect(f"rep:{message.guild.id}:{message.id}"):
            return
        total = await self.service.total(message.guild.id, target.id)
        await message.reply(embed=rep_embed(message.author, target, reason, total))

    # ── Slash commands ───────────────────────────────────────────────────

    @app_commands.command(name="rep", description="Dar reputación a un usuario", extras={"module": "reputation", "public": True, "always_on": True})
    @app_commands.guild_only()
    @app_commands.describe(usuario="Usuario a dar rep", razon="Razón (opcional)")
    async def rep(self, interaction: discord.Interaction, usuario: discord.User, razon: str | None = None) -> None:
        await self._give(interaction, usuario, (razon or "").strip() or None, slash_style=True)

    @app_commands.command(name="toprep", description="Ver el ranking de reputación del servidor",
                          extras={"module": "reputation", "cooldown": 5})
    @app_commands.guild_only()
    @app_commands.describe(pagina="Página del ranking")
    async def toprep(self, interaction: discord.Interaction, pagina: app_commands.Range[int, 1] = 1) -> None:
        guild = interaction.guild
        assert guild is not None
        page_size = 10
        async with self.bot.db.session() as session:
            rows = (await session.execute(
                select(Reputation.user_id, func.count()).where(Reputation.guild_id == str(guild.id))
                .group_by(Reputation.user_id).order_by(func.count().desc())
                .offset((pagina - 1) * page_size).limit(page_size))).all()
            total_users = await session.scalar(select(func.count(func.distinct(Reputation.user_id))).where(
                Reputation.guild_id == str(guild.id)))
        if not rows:
            await interaction.response.send_message(embed=discord.Embed(
                color=OK, title="🏆 Ranking de Reputación", timestamp=discord.utils.utcnow(),
                description="Aún no hay reputación registrada en este servidor."), ephemeral=True)
            return
        lines = []
        for i, (user_id, count) in enumerate(rows):
            rank = (pagina - 1) * page_size + i + 1
            member = guild.get_member(int(user_id))
            name = member.name if member else f"<@{user_id}>"
            lines.append(f"{MEDALS[rank - 1] if rank <= 3 else f'**{rank}.**'} {name} — **{count}** rep")
        pages = max(1, -(-(total_users or 0) // page_size))
        embed = discord.Embed(color=OK, title="🏆 Ranking de Reputación", description="\n".join(lines),
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"Página {pagina} de {pages} • {total_users} usuarios con rep")
        await interaction.response.send_message(embed=embed)

    reputacion = app_commands.Group(name="reputacion", description="Sistema de reputación", guild_only=True,
                                    extras={"module": "reputation"})

    @reputacion.command(name="dar", description="Dar +1 reputación a un usuario")
    @app_commands.describe(usuario="Usuario a quien dar rep", razon="Razón (opcional)")
    async def give(self, interaction: discord.Interaction, usuario: discord.User, razon: str | None = None) -> None:
        await self._give(interaction, usuario, razon or "", slash_style=False)

    @reputacion.command(name="quitar", description="Quitar reputación a un usuario")
    @app_commands.describe(usuario="Usuario a quien quitar rep", cantidad="Cantidad a quitar (default 1)")
    async def take(self, interaction: discord.Interaction, usuario: discord.User,
                   cantidad: app_commands.Range[int, 1, 100] = 1) -> None:
        if not interaction.permissions.manage_guild:
            await interaction.response.send_message(
                "Necesitas el permiso de **Gestionar servidor** para quitar reputación.", ephemeral=True)
            return
        if usuario.bot:
            await interaction.response.send_message("No puedes quitar reputación a bots.", ephemeral=True)
            return
        removed = await self.service.remove_recent(interaction.guild_id or 0, usuario.id, cantidad)
        if not removed:
            await interaction.response.send_message("Ese usuario no tiene reputación para quitar en este servidor.",
                                                    ephemeral=True)
            return
        total = await self.service.total(interaction.guild_id or 0, usuario.id)
        embed = discord.Embed(color=module_color("reputation"), description=f"🗑️ Quitaste **-{removed} rep** a {usuario.mention}",
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"{usuario.name} ahora tiene {total} rep")
        await interaction.response.send_message(embed=embed)

    @reputacion.command(name="ingresar", description="Ingresar reputacion manualmente a un usuario")
    @app_commands.describe(user="Usuario que recibira la reputacion", cantidad="Cantidad de reputacion a ingresar",
                           razon="Razon del ingreso")
    async def add(self, interaction: discord.Interaction, user: discord.User, cantidad: app_commands.Range[int, 1],
                  razon: app_commands.Range[str, 1, 500]) -> None:
        if not interaction.permissions.administrator:
            await interaction.response.send_message("Este comando solo puede ser usado por administradores.", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("No puedes ingresar reputacion a bots.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.service.add(interaction.guild_id or 0, user.id, interaction.user.id, cantidad, razon.strip())
        total = await self.service.total(interaction.guild_id or 0, user.id)
        embed = discord.Embed(color=module_color("reputation"), title="Reputacion ingresada",
                              description=f"Se ingresaron **+{cantidad} rep** a {user.mention}.", timestamp=discord.utils.utcnow())
        embed.add_field(name="Razon", value=razon.strip()[:1024], inline=False)
        embed.add_field(name="Total actual", value=f"{total} rep", inline=True)
        embed.set_footer(text=f"Ingresado por {interaction.user.name}")
        await interaction.followup.send(embed=embed)

    @reputacion.command(name="migrar", description="Migrar toda la reputacion de un usuario a otro")
    @app_commands.describe(de="Usuario que perdera la reputacion", a="Usuario que recibira la reputacion",
                           anunciar="Mostrar un cartel publico de la migracion", razon="Razon de la migracion")
    async def migrate(self, interaction: discord.Interaction, de: discord.User, a: discord.User, anunciar: bool = False,
                      razon: app_commands.Range[str, 1, 500] | None = None) -> None:
        if not interaction.permissions.administrator:
            await interaction.response.send_message("Este comando solo puede ser usado por administradores.", ephemeral=True)
            return
        if de.id == a.id:
            await interaction.response.send_message("El usuario de origen y destino no pueden ser el mismo.", ephemeral=True)
            return
        if de.bot or a.bot:
            await interaction.response.send_message("No puedes migrar reputacion desde o hacia bots.", ephemeral=True)
            return
        reason = (razon or "").strip() or DEFAULT_MIGRATION_REASON
        await interaction.response.defer(ephemeral=not anunciar)
        moved = await self.service.migrate(interaction.guild_id or 0, de.id, a.id, reason)
        if not moved:
            await interaction.followup.send("El usuario de origen no tiene reputacion para migrar.", ephemeral=True)
            return
        total = await self.service.total(interaction.guild_id or 0, a.id)
        embed = discord.Embed(color=module_color("reputation"), title="Reputacion migrada",
                              description=f"Se migraron **{moved} rep** de {de.mention} a {a.mention}.",
                              timestamp=discord.utils.utcnow())
        embed.add_field(name="Razon", value=reason[:1024], inline=False)
        embed.add_field(name="Total del destino", value=f"{total} rep", inline=True)
        embed.set_footer(text=f"Migrado por {interaction.user.name}")
        await interaction.followup.send(embed=embed, ephemeral=not anunciar)

    @reputacion.command(name="ranking", description="Ver el ranking de reputación del servidor")
    async def ranking(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        rows = await self.service.leaderboard(interaction.guild_id or 0, 50)
        if not rows:
            await interaction.followup.send("Aún no hay reputación en este servidor.", ephemeral=True)
            return
        lines = [f"{MEDALS[i] if i < 3 else f'**{i + 1}.**'} <@{uid}> — **{n}** rep" for i, (uid, n) in enumerate(rows[:15])]
        await interaction.followup.send(embed=discord.Embed(color=module_color("reputation"), title="🏆 Ranking de Reputación",
                                                            description="\n".join(lines), timestamp=discord.utils.utcnow()))

    @reputacion.command(name="recibir", description="Ver la reputación recibida por un usuario")
    @app_commands.describe(usuario="Usuario a consultar (por defecto tú)")
    async def received(self, interaction: discord.Interaction, usuario: discord.User | None = None) -> None:
        user = usuario or interaction.user
        guild_id = interaction.guild_id or 0
        total = await self.service.total(guild_id, user.id)
        recent = await self.service.recent_received(guild_id, user.id)
        embed = discord.Embed(color=module_color("reputation"), title=f"Reputación recibida — {user.name}")
        embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        embed.add_field(name="⭐ Total", value=f"{total} rep", inline=True)
        if not recent:
            embed.description = "Este usuario aún no tiene reputación reciente en este servidor."
        else:
            lines = [f"{discord_ts(r.created_at)} de <@{r.giver_id}>{f' — *{r.reason}*' if r.reason else ''}" for r in recent]
            embed.add_field(name="📜 Historial reciente", value="\n".join(lines)[:1024], inline=False)
        await interaction.response.send_message(embed=embed)

    # ── Dashboard API ────────────────────────────────────────────────────

    async def _leaderboard_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        rows = await self.service.leaderboard(str(body.get("guildId")), int(body.get("limit") or 50))
        return json_response([{"userId": uid, "rep": n} for uid, n in rows])

    async def _add_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        user_id, reason = str(body.get("userId", "")).strip(), str(body.get("razon", "")).strip()
        try:
            amount = int(body.get("cantidad"))
        except (TypeError, ValueError):
            amount = 0
        if not is_snowflake(user_id):
            raise HttpError(400, "ID de usuario invalido")
        if amount < 1:
            raise HttpError(400, "La cantidad debe ser 1 o mayor")
        if not reason:
            raise HttpError(400, "La razon es obligatoria")
        guild_id = str(body.get("guildId"))
        await self.service.add(guild_id, user_id, str(body.get("giverId") or "dashboard"), amount, reason)
        return json_response({"success": True, "userId": user_id, "added": amount,
                              "total": await self.service.total(guild_id, user_id)}, 201)

    async def _migrate_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        from_id, to_id = str(body.get("fromUserId", "")).strip(), str(body.get("toUserId", "")).strip()
        reason = str(body.get("razon") or DEFAULT_MIGRATION_REASON).strip() or DEFAULT_MIGRATION_REASON
        if not is_snowflake(from_id) or not is_snowflake(to_id):
            raise HttpError(400, "IDs de usuario invalidos")
        if from_id == to_id:
            raise HttpError(400, "El usuario de origen y destino no pueden ser el mismo")
        guild_id = str(body.get("guildId"))
        moved = await self.service.migrate(guild_id, from_id, to_id, reason)
        if not moved:
            raise HttpError(404, "El usuario de origen no tiene reputacion para migrar")
        return json_response({"success": True, "fromUserId": from_id, "toUserId": to_id, "moved": moved,
                              "total": await self.service.total(guild_id, to_id), "reason": reason})


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(ReputationCog(bot))
