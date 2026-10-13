"""Invite tracking: who invited whom, fake/left detection, logs and leaderboards."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import unicodedata
from dataclasses import dataclass
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, func, select, update

from markets_bot.bot import MarketsBot
from markets_bot.core.utils import OK, WARN, discord_ts, module_color
from markets_bot.db.models import Invite, ModAction

log = logging.getLogger(__name__)

INVITE_LOG_CHANNEL = "𝐈𝐧𝐯𝐢𝐭𝐚𝐜𝐢𝐨𝐧𝐞𝐬"
FAKE_ACCOUNT_AGE = timedelta(days=7)
DELETED_INVITE_GRACE_SECONDS = 15
MEDALS = ("🥇", "🥈", "🥉")


@dataclass(slots=True)
class CachedInvite:
    code: str
    uses: int
    inviter_id: int | None
    deleted_at: float = 0.0


@dataclass(slots=True)
class JoinResult:
    code: str
    inviter_id: int


def _normalize_channel_name(name: str) -> str:
    """'𝐈𝐧𝐯𝐢𝐭𝐚𝐜𝐢𝐨𝐧𝐞𝐬' / 'invitaciónes' -> 'invitaciones' (fancy unicode letters included)."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed.lower() if c.isascii() and c.isalnum())


class Invites(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self._cache: dict[int, dict[str, CachedInvite]] = {}
        self._deleted: dict[int, dict[str, CachedInvite]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    # ── Cache ────────────────────────────────────────────────────────────

    async def _snapshot(self, guild: discord.Guild) -> dict[str, CachedInvite]:
        invites = await guild.invites()
        return {
            inv.code: CachedInvite(inv.code, inv.uses or 0, inv.inviter.id if inv.inviter else None)
            for inv in invites
        }

    async def refresh(self, guild: discord.Guild) -> None:
        try:
            self._cache[guild.id] = await self._snapshot(guild)
        except discord.HTTPException:
            log.warning("Could not fetch invites for %s (%s)", guild.name, guild.id)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            if (await self.bot.configs.get(guild.id)).invites_enabled:
                await self.refresh(guild)
        log.info("Invite cache populated")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        if (await self.bot.configs.get(guild.id)).invites_enabled:
            await self.refresh(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        guild = invite.guild if isinstance(invite.guild, discord.Guild) else None
        if guild is None or not (await self.bot.configs.get(guild.id)).invites_enabled:
            return
        self._cache.setdefault(guild.id, {})[invite.code] = CachedInvite(
            invite.code, invite.uses or 0, invite.inviter.id if invite.inviter else None
        )
        embed = discord.Embed(color=module_color("invites"), title="Invitacion creada", timestamp=discord.utils.utcnow())
        embed.add_field(name="Codigo", value=f"`{invite.code}`", inline=True)
        embed.add_field(
            name="Creada por",
            value=f"{invite.inviter.mention}\nID: `{invite.inviter.id}`" if invite.inviter else "Desconocido",
            inline=True,
        )
        embed.add_field(name="Canal", value=f"<#{invite.channel.id}>" if invite.channel else "Desconocido", inline=True)
        embed.add_field(name="Usos maximos", value=str(invite.max_uses) if invite.max_uses else "Ilimitado", inline=True)
        embed.add_field(name="Expira", value=discord_ts(invite.expires_at) if invite.expires_at else "Nunca", inline=True)
        await self.send_log(guild, embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        guild = invite.guild if isinstance(invite.guild, discord.Guild) else None
        if guild is None or not (await self.bot.configs.get(guild.id)).invites_enabled:
            return
        cached = self._cache.get(guild.id, {}).pop(invite.code, None)
        if cached:
            cached.deleted_at = time.monotonic()
            self._deleted.setdefault(guild.id, {})[invite.code] = cached
        embed = discord.Embed(color=module_color("invites"), title="Invitacion eliminada", timestamp=discord.utils.utcnow())
        embed.add_field(name="Codigo", value=f"`{invite.code}`", inline=True)
        embed.add_field(name="Canal", value=f"<#{invite.channel.id}>" if invite.channel else "Desconocido", inline=True)
        await self.send_log(guild, embed)

    # ── Log channel ──────────────────────────────────────────────────────

    async def log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        preferred = discord.utils.get(guild.text_channels, name=INVITE_LOG_CHANNEL)
        if preferred:
            return preferred
        existing = discord.utils.find(
            lambda c: "invitaciones" in _normalize_channel_name(c.name), guild.text_channels
        )
        if existing:
            return existing
        if not guild.me.guild_permissions.manage_channels:
            return None
        try:
            return await guild.create_text_channel(INVITE_LOG_CHANNEL, reason="Canal de logs de invitaciones")
        except discord.HTTPException as exc:
            log.warning("Could not create invite log channel in %s: %s", guild.name, exc)
            return None

    async def send_log(self, guild: discord.Guild, embed: discord.Embed) -> None:
        if not (await self.bot.configs.get(guild.id)).invites_enabled:
            return
        channel = await self.log_channel(guild)
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            log.warning("Failed to send invite log in %s: %s", guild.name, exc)

    # ── Join detection ───────────────────────────────────────────────────

    async def _detect_used_invite(self, guild: discord.Guild) -> JoinResult | None:
        """Diff invite use counts. Serialized per guild so two simultaneous joins don't share one invite."""
        lock = self._locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            old = self._cache.get(guild.id, {})
            new = await self._snapshot(guild)
            candidates = []
            for code, inv in new.items():
                before = old.get(code)
                if inv.inviter_id is None and before:
                    inv.inviter_id = before.inviter_id
                if before and inv.uses > before.uses:
                    candidates.append((inv.uses - before.uses, inv))
            used: JoinResult | None = None
            candidates.sort(key=lambda item: item[0], reverse=True)
            if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
                top = candidates[0][1]
                if top.inviter_id:
                    used = JoinResult(top.code, top.inviter_id)
                # Only consume one use so a concurrent join can still be attributed.
                top.uses = min(top.uses, old[top.code].uses + 1)

            # One-use invites disappear right before the join event arrives.
            deleted = self._deleted.get(guild.id, {})
            cutoff = time.monotonic() - DELETED_INVITE_GRACE_SECONDS
            if used is None:
                recent = [d for d in deleted.values() if d.deleted_at >= cutoff]
                if len(recent) == 1 and recent[0].inviter_id:
                    used = JoinResult(recent[0].code, recent[0].inviter_id)
                    deleted.pop(recent[0].code, None)
            for code in [c for c, d in deleted.items() if d.deleted_at < cutoff]:
                deleted.pop(code, None)

            self._cache[guild.id] = new
            return used

    async def _discord_join_source(self, guild: discord.Guild, user_id: int) -> tuple[int | None, str | None] | None:
        """Ask Discord which invite a member used (Server Settings → Members). Retries while Discord indexes."""
        route = discord.http.Route("POST", "/guilds/{guild_id}/members-search", guild_id=guild.id)
        body = {"limit": 1, "or_query": {"user_id": {"or_query": [str(user_id)]}}}
        for attempt in range(4):
            if attempt:
                await asyncio.sleep(1.5)
            try:
                result = await self.bot.http.request(route, json=body)
            except discord.HTTPException as exc:
                log.warning("Join-source lookup failed for %s: %s", user_id, exc)
                return None
            for entry in result.get("members", []):
                if entry["member"]["user"]["id"] == str(user_id) and (
                    entry.get("inviter_id") or entry.get("source_invite_code")
                ):
                    inviter = entry.get("inviter_id")
                    return (int(inviter) if inviter else None, entry.get("source_invite_code"))
        return None

    async def track_join(self, member: discord.Member) -> int | None:
        """Record which invite ``member`` used. Returns the inviter's ID when known."""
        guild = member.guild
        try:
            guess = await self._detect_used_invite(guild)
        except discord.HTTPException:
            guess = None
        source = await self._discord_join_source(guild, member.id)
        if source and source[0]:
            used: JoinResult | None = JoinResult(source[1] or (guess.code if guess else "desconocido"), source[0])
        else:
            used = guess
        if used is None:
            log.warning("Could not determine who invited %s (%s) in %s", member, member.id, guild.name)
            return None

        is_fake = discord.utils.utcnow() - member.created_at < FAKE_ACCOUNT_AGE
        async with self.bot.db.session() as session:
            session.add(Invite(
                guild_id=str(guild.id), inviter_id=str(used.inviter_id), invited_id=str(member.id),
                code=used.code, fake=is_fake,
            ))
        banned = await self.banned_invitees(guild.id, used.inviter_id)

        embed = discord.Embed(color=OK, title="Miembro entro por invitacion", timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario acepto", value=f"{member.mention}\nID: `{member.id}`", inline=True)
        embed.add_field(name="Invitado por", value=f"<@{used.inviter_id}>\nID: `{used.inviter_id}`", inline=True)
        embed.add_field(name="Codigo", value=f"`{used.code}`", inline=True)
        embed.add_field(name="Cuenta creada", value=discord_ts(member.created_at), inline=True)
        embed.add_field(name="Invitados baneados de ese invitador", value=str(banned), inline=True)
        embed.add_field(name="Fake", value="Si" if is_fake else "No", inline=True)
        await self.send_log(guild, embed)

        if banned >= 2:
            config = await self.bot.configs.get(guild.id)
            alert = discord.Embed(
                color=WARN, title="Invitador con historial de baneos",
                description=f"{member.mention} entro usando una invitacion de <@{used.inviter_id}>.",
                timestamp=discord.utils.utcnow(),
            )
            alert.add_field(name="Nuevo miembro", value=f"{member.mention}\nID: `{member.id}`", inline=True)
            alert.add_field(name="Invitador", value=f"<@{used.inviter_id}>\nID: `{used.inviter_id}`", inline=True)
            alert.add_field(name="Invitados baneados", value=str(banned), inline=True)
            alert.add_field(name="Codigo", value=f"`{used.code}`", inline=True)
            channel_id = config.mod_log_channel_id or config.join_leave_log_channel_id
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if isinstance(channel, discord.TextChannel):
                with contextlib.suppress(discord.HTTPException):
                    await channel.send(embed=alert)
        log.info("%s joined %s via %s by %s%s; inviter banned-invite count=%d",
                 member, guild.name, used.code, used.inviter_id, " (FAKE)" if is_fake else "", banned)
        return used.inviter_id

    async def banned_invitees(self, guild_id: int, inviter_id: int | str) -> int:
        async with self.bot.db.session() as session:
            invited = select(Invite.invited_id).where(
                Invite.guild_id == str(guild_id), Invite.inviter_id == str(inviter_id)
            ).distinct()
            return int(await session.scalar(
                select(func.count()).select_from(ModAction).where(
                    ModAction.guild_id == str(guild_id),
                    ModAction.user_id.in_(invited),
                    ModAction.action.in_(("ban", "tempban")),
                )
            ) or 0)

    async def last_invite_for(self, guild_id: int, user_id: int) -> Invite | None:
        async with self.bot.db.session() as session:
            return (await session.execute(
                select(Invite).where(Invite.guild_id == str(guild_id), Invite.invited_id == str(user_id))
                .order_by(Invite.created_at.desc()).limit(1)
            )).scalar_one_or_none()

    async def mark_left(self, guild_id: int, user_id: int) -> None:
        async with self.bot.db.session() as session:
            await session.execute(
                update(Invite)
                .where(Invite.guild_id == str(guild_id), Invite.invited_id == str(user_id), Invite.left.is_(False))
                .values(left=True)
            )

    # ── Commands ─────────────────────────────────────────────────────────

    async def _counts(self, guild_id: int, user_id: int) -> dict[str, int]:
        g, u = str(guild_id), str(user_id)
        base = select(func.count()).select_from(Invite).where(Invite.guild_id == g, Invite.inviter_id == u)
        async with self.bot.db.session() as session:
            total = await session.scalar(base)
            fake = await session.scalar(base.where(Invite.fake.is_(True)))
            left = await session.scalar(base.where(Invite.left.is_(True)))
            valid = await session.scalar(base.where(Invite.fake.is_(False), Invite.left.is_(False)))
        return {"total": total or 0, "fake": fake or 0, "left": left or 0, "valid": valid or 0}

    @app_commands.command(name="invitacion", description="Ver quien invito a un usuario y sus estadisticas",
                          extras={"module": "invites", "cooldown": 5})
    @app_commands.describe(usuario="Usuario a consultar")
    @app_commands.guild_only()
    async def invitacion(self, interaction: discord.Interaction, usuario: discord.User | None = None) -> None:
        assert interaction.guild_id is not None
        user = usuario or interaction.user
        joined_by = await self.last_invite_for(interaction.guild_id, user.id)
        counts = await self._counts(interaction.guild_id, user.id)
        async with self.bot.db.session() as session:
            recent = (await session.execute(
                select(Invite).where(Invite.guild_id == str(interaction.guild_id), Invite.inviter_id == str(user.id))
                .order_by(Invite.created_at.desc()).limit(5)
            )).scalars().all()

        if joined_by:
            lines = [f"<@{joined_by.inviter_id}>", f"Codigo: `{joined_by.code}`", f"Fecha: {discord_ts(joined_by.created_at)}"]
            if joined_by.fake:
                lines.append("Marcada como fake")
            if joined_by.left:
                lines.append("Ese usuario ya salio")
            invited_by = "\n".join(lines)
        else:
            invited_by = "No tengo registro. Puede ser invite viejo, vanity URL, o el bot no tenia cache de invites."
        recent_text = "\n".join(
            f"<@{inv.invited_id}> - `{inv.code}` - {discord_ts(inv.created_at)}"
            f"{' fake' if inv.fake else ''}{' salio' if inv.left else ''}"
            for inv in recent
        ) or "No tiene invitados registrados."

        embed = discord.Embed(color=module_color("invites"), timestamp=discord.utils.utcnow())
        embed.set_author(name=f"Invitacion de {user.name}", icon_url=user.display_avatar.url)
        embed.add_field(name="Quien lo invito", value=invited_by, inline=False)
        embed.add_field(
            name="Stats como invitador",
            value=f"Validas: **{counts['valid']}**\nTotal: **{counts['total']}**\n"
                  f"Fake: **{counts['fake']}**\nSalieron: **{counts['left']}**",
            inline=True,
        )
        embed.add_field(name="Ultimos invitados", value=recent_text[:1024], inline=False)
        embed.set_footer(text=f"ID: {user.id}")
        await interaction.response.send_message(embed=embed)

    invitaciones = app_commands.Group(
        name="invitaciones", description="Comandos de seguimiento de invitaciones", guild_only=True,
        extras={"module": "invites", "cooldown": 5},
    )

    @invitaciones.command(name="info", description="Ver estadísticas de invitaciones de un usuario")
    @app_commands.describe(usuario="Usuario a consultar")
    async def inv_info(self, interaction: discord.Interaction, usuario: discord.User | None = None) -> None:
        assert interaction.guild_id is not None
        user = usuario or interaction.user
        c = await self._counts(interaction.guild_id, user.id)
        embed = discord.Embed(color=module_color("invites"), timestamp=discord.utils.utcnow())
        embed.set_author(name=f"Invitaciones de {user.name}", icon_url=user.display_avatar.url)
        embed.add_field(name="Total", value=str(c["valid"]), inline=True)
        embed.add_field(name="Regulares", value=str(c["total"] - c["fake"]), inline=True)
        embed.add_field(name="Falsas", value=str(c["fake"]), inline=True)
        embed.add_field(name="Se fueron", value=str(c["left"]), inline=True)
        embed.set_footer(text="Invitaciones válidas: cuentas no falsas que siguen en el servidor")
        await interaction.response.send_message(embed=embed)

    @invitaciones.command(name="ranking", description="Ver el ranking de invitaciones")
    async def inv_ranking(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        async with self.bot.db.session() as session:
            rows = (await session.execute(
                select(Invite.inviter_id, func.count().label("n"))
                .where(Invite.guild_id == str(interaction.guild.id), Invite.fake.is_(False), Invite.left.is_(False))
                .group_by(Invite.inviter_id).order_by(func.count().desc()).limit(15)
            )).all()
        if not rows:
            await interaction.response.send_message("Aún no hay datos de invitaciones.", ephemeral=True)
            return
        lines = [
            f"{MEDALS[i] if i < 3 else f'**{i + 1}.**'} <@{inviter}> — **{n}** invitaciones"
            for i, (inviter, n) in enumerate(rows)
        ]
        embed = discord.Embed(color=module_color("invites"), title="Ranking de Invitaciones",
                              description="\n".join(lines), timestamp=discord.utils.utcnow())
        embed.set_footer(text=interaction.guild.name)
        await interaction.response.send_message(embed=embed)

    @invitaciones.command(name="quien", description="Ver quién invitó a un usuario específico")
    @app_commands.describe(usuario="Usuario a consultar")
    async def inv_quien(self, interaction: discord.Interaction, usuario: discord.User) -> None:
        assert interaction.guild_id is not None
        record = await self.last_invite_for(interaction.guild_id, usuario.id)
        if record is None:
            await interaction.response.send_message(
                f"No se pudo determinar quién invitó a **{usuario.name}**. Puede que se haya unido por una URL "
                "de vanidad o que no se rastrearon los datos de invitación.",
                ephemeral=True,
            )
            return
        text = (
            f"**{usuario.name}** fue invitado por <@{record.inviter_id}> usando el código `{record.code}`"
            f"{' ⚠️ (marcada como falsa)' if record.fake else ''}{' (ya se fue)' if record.left else ''}"
        )
        await interaction.response.send_message(
            embed=discord.Embed(color=module_color("invites"), description=text, timestamp=discord.utils.utcnow())
        )

    @invitaciones.command(name="reiniciar", description="Reiniciar datos de invitaciones de un usuario (solo admins)")
    @app_commands.describe(usuario="Usuario a reiniciar")
    async def inv_reiniciar(self, interaction: discord.Interaction, usuario: discord.User) -> None:
        if not interaction.permissions.administrator:
            await interaction.response.send_message(
                "Solo los administradores pueden reiniciar datos de invitaciones.", ephemeral=True
            )
            return
        async with self.bot.db.session() as session:
            result = await session.execute(
                delete(Invite).where(
                    Invite.guild_id == str(interaction.guild_id), Invite.inviter_id == str(usuario.id)
                )
            )
        await interaction.response.send_message(
            f"Se reiniciaron **{result.rowcount}** registros de invitación de {usuario.name}.", ephemeral=True
        )


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Invites(bot))
