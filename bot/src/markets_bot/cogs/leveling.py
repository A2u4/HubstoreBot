"""Leveling (MEE6/Nekotina style): message XP, rank cards, leaderboard, role rewards."""

from __future__ import annotations

import asyncio
import io
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from markets_bot.bot import MarketsBot
from markets_bot.cogs.members import avatar_png
from markets_bot.core.audit import text_channel
from markets_bot.core.cache import TtlCache
from markets_bot.core.pipeline import MessagePipeline
from markets_bot.core.utils import module_color, render_template
from markets_bot.db.base import new_id
from markets_bot.db.models import GuildConfig, LevelReward
from markets_bot.services.leveling import LevelService, Progress, total_xp_for
from markets_bot.services.rank_card import RankCardInput, render_rank_card

log = logging.getLogger(__name__)
PAGE = 10
COLOR = module_color("leveling")
ANNOUNCE_OFF = "off"  # levelUpChannelId value that disables level-up messages


class Leveling(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self.levels = LevelService(bot.db)
        self._last_xp: TtlCache[float] = TtlCache(3600, 50_000)
        self._rewards: TtlCache[list[LevelReward]] = TtlCache(300, 500)
        bot.pipeline.register("leveling", self.on_message_xp, MessagePipeline.LEVELING)

    async def cog_unload(self) -> None:
        self.bot.pipeline.unregister("leveling")

    @commands.Cog.listener()
    async def on_cache_invalidate(self, guild_id: str | None) -> None:
        if guild_id:
            self._rewards.delete(guild_id)
        else:
            self._rewards.clear()

    # ── XP from messages ─────────────────────────────────────────────────

    async def on_message_xp(self, message: discord.Message, config: GuildConfig) -> None:
        if not config.leveling_enabled or message.guild is None or not isinstance(message.author, discord.Member):
            return
        if str(message.channel.id) in (config.leveling_ignored_channel_ids or []) or (
                getattr(message.channel, "parent_id", None)
                and str(message.channel.parent_id) in (config.leveling_ignored_channel_ids or [])):  # type: ignore[union-attr]
            return
        ignored_roles = set(config.leveling_ignored_role_ids or [])
        if ignored_roles and any(str(r.id) in ignored_roles for r in message.author.roles):
            return
        key = f"{message.guild.id}:{message.author.id}"
        now = time.monotonic()
        last = self._last_xp.get(key)
        if last is not None and now - last < config.xp_cooldown_seconds:
            return
        self._last_xp.set(key, now)
        result = await self.levels.add_message_xp(str(message.guild.id), str(message.author.id),
                                                  config.xp_per_message_min, config.xp_per_message_max)
        if result is not None:
            old, new, _ = result
            if new > old:
                await self._on_level_up(message.author, new, config, message.channel)

    async def _on_level_up(self, member: discord.Member, level: int, config: GuildConfig,
                           fallback: discord.abc.Messageable | None) -> None:
        await self.apply_rewards(member, level, config)
        if config.level_up_channel_id == ANNOUNCE_OFF:
            return
        channel = text_channel(member.guild, config.level_up_channel_id) or fallback
        if channel is None:
            return
        text = render_template(config.level_up_message or "🎉 {user} subió a **nivel {level}**", {
            "user": member.mention, "username": member.name, "displayName": member.display_name,
            "level": str(level), "server": member.guild.name})
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.HTTPException:
            pass

    async def _guild_rewards(self, guild_id: int) -> list[LevelReward]:
        key = str(guild_id)
        cached = self._rewards.get(key)
        if cached is not None:
            return cached
        async with self.bot.db.session() as session:
            rows = list((await session.execute(select(LevelReward).where(LevelReward.guild_id == key)
                                               .order_by(LevelReward.level))).scalars())
        self._rewards.set(key, rows)
        return rows

    async def apply_rewards(self, member: discord.Member, level: int, config: GuildConfig) -> None:
        """Give every reward up to ``level``; without stacking keep only the highest tier's roles."""
        rewards = await self._guild_rewards(member.guild.id)
        if not rewards:
            return
        earned = [r for r in rewards if r.level <= level]
        if not config.level_rewards_stack and earned:
            top = max(r.level for r in earned)
            keep = {r.role_id for r in earned if r.level == top}
        else:
            keep = {r.role_id for r in earned}
        all_reward_ids = {r.role_id for r in rewards}
        current = {str(r.id) for r in member.roles}
        add = [role for rid in keep - current if (role := member.guild.get_role(int(rid)))]
        remove = [role for rid in (all_reward_ids - keep) & current if (role := member.guild.get_role(int(rid)))]
        try:
            if add:
                await member.add_roles(*add, reason=f"Recompensa de nivel {level}")
            if remove:
                await member.remove_roles(*remove, reason=f"Recompensa de nivel {level} (sin acumular)")
        except discord.HTTPException as exc:
            log.warning("Could not apply level rewards in %s: %s", member.guild.id, exc)

    # ── /nivel and /top-niveles ──────────────────────────────────────────

    @app_commands.command(name="nivel", description="Ver tu tarjeta de nivel o la de otro miembro",
                          extras={"module": "leveling", "cooldown": 5, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(usuario="Miembro a consultar (por defecto: tú)")
    async def rank(self, interaction: discord.Interaction, usuario: discord.Member | None = None) -> None:
        member = usuario or interaction.user
        assert interaction.guild is not None
        if member.bot:
            await interaction.response.send_message("Los bots no ganan XP.", ephemeral=True)
            return
        await interaction.response.defer()
        gid = str(interaction.guild.id)
        row = await self.levels.get(gid, str(member.id))
        progress = Progress.of(row.xp if row else 0)
        position = await self.levels.rank(gid, progress.xp)
        png = await asyncio.to_thread(render_rank_card, RankCardInput(
            avatar_png=await avatar_png(member), name=member.display_name, level=progress.level, rank=position,
            current=progress.current, needed=progress.needed, total_xp=progress.xp))
        await interaction.followup.send(file=discord.File(io.BytesIO(png), filename="nivel.png"))

    @app_commands.command(name="top-niveles", description="Ranking de niveles del servidor",
                          extras={"module": "leveling", "cooldown": 5, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(pagina="Página del ranking")
    async def leaderboard(self, interaction: discord.Interaction, pagina: app_commands.Range[int, 1, 500] = 1) -> None:
        assert interaction.guild is not None
        guild = interaction.guild
        cog = self

        async def page_embed(page: int) -> tuple[discord.Embed, int]:
            rows, total = await cog.levels.leaderboard(str(guild.id), page * PAGE, PAGE)
            pages = max(1, -(-total // PAGE))
            medals = {0: "🥇", 1: "🥈", 2: "🥉"}
            lines = []
            for i, row in enumerate(rows):
                position = page * PAGE + i
                progress = Progress.of(row.xp)
                lines.append(f"{medals.get(position, f'`#{position + 1}`')} <@{row.user_id}> — Nivel **{progress.level}** "
                             f"· {row.xp:,} XP · {row.messages:,} msgs")
            embed = discord.Embed(color=COLOR, title=f"📈 Ranking de niveles — {guild.name}",
                                  description="\n".join(lines) or "_Nadie tiene XP todavía._")
            embed.set_footer(text=f"Página {page + 1} de {pages} • {total} miembros con XP")
            return embed, pages

        embed, pages = await page_embed(pagina - 1)

        class Pager(discord.ui.View):
            def __init__(self, page: int) -> None:
                super().__init__(timeout=120)
                self.page = page
                self._sync()

            def _sync(self) -> None:
                self.prev.disabled = self.page <= 0
                self.next.disabled = self.page >= pages - 1

            async def interaction_check(self, i: discord.Interaction) -> bool:
                return i.user.id == interaction.user.id

            async def _go(self, i: discord.Interaction, delta: int) -> None:
                nonlocal pages
                self.page += delta
                new_embed, pages = await page_embed(self.page)
                self._sync()
                await i.response.edit_message(embed=new_embed, view=self)

            @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
            async def prev(self, i: discord.Interaction, _: discord.ui.Button[Pager]) -> None:
                await self._go(i, -1)

            @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
            async def next(self, i: discord.Interaction, _: discord.ui.Button[Pager]) -> None:
                await self._go(i, 1)

        await interaction.response.send_message(embed=embed, view=Pager(pagina - 1) if pages > 1 else discord.utils.MISSING)

    # ── /niveles (admin) ─────────────────────────────────────────────────

    admin = app_commands.Group(name="niveles", description="Administrar el sistema de niveles", guild_only=True,
                               default_permissions=discord.Permissions(manage_guild=True),
                               extras={"module": "leveling", "cooldown": 3, "permissions": ["manage_guild"]})

    async def _after_change(self, member: discord.Member, level: int) -> None:
        config = await self.bot.configs.get(member.guild.id)
        await self.apply_rewards(member, level, config)

    @admin.command(name="dar-xp", description="Dar XP a un miembro")
    @app_commands.describe(usuario="Miembro", cantidad="XP a dar")
    async def give_xp(self, interaction: discord.Interaction, usuario: discord.Member,
                      cantidad: app_commands.Range[int, 1, 10_000_000]) -> None:
        await self.levels.add_xp(str(usuario.guild.id), str(usuario.id), cantidad)
        row = await self.levels.get(str(usuario.guild.id), str(usuario.id))
        level = row.level if row else 0
        await self._after_change(usuario, level)
        await interaction.response.send_message(f"✅ {usuario.mention} recibió **{cantidad:,} XP** (nivel {level}).",
                                                ephemeral=True)

    @admin.command(name="quitar-xp", description="Quitar XP a un miembro")
    @app_commands.describe(usuario="Miembro", cantidad="XP a quitar")
    async def take_xp(self, interaction: discord.Interaction, usuario: discord.Member,
                      cantidad: app_commands.Range[int, 1, 10_000_000]) -> None:
        row = await self.levels.get(str(usuario.guild.id), str(usuario.id))
        level = await self.levels.set_xp(str(usuario.guild.id), str(usuario.id), (row.xp if row else 0) - cantidad)
        await self._after_change(usuario, level)
        await interaction.response.send_message(f"✅ Se quitaron **{cantidad:,} XP** a {usuario.mention} (nivel {level}).",
                                                ephemeral=True)

    @admin.command(name="establecer-nivel", description="Fijar el nivel de un miembro")
    @app_commands.describe(usuario="Miembro", nivel="Nuevo nivel")
    async def set_level(self, interaction: discord.Interaction, usuario: discord.Member,
                        nivel: app_commands.Range[int, 0, 500]) -> None:
        level = await self.levels.set_xp(str(usuario.guild.id), str(usuario.id), total_xp_for(nivel))
        await self._after_change(usuario, level)
        await interaction.response.send_message(f"✅ {usuario.mention} ahora es **nivel {level}**.", ephemeral=True)

    @admin.command(name="reiniciar", description="Reiniciar el XP de un miembro")
    @app_commands.describe(usuario="Miembro")
    async def reset(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        await self.levels.set_xp(str(usuario.guild.id), str(usuario.id), 0)
        await self._after_change(usuario, 0)
        await interaction.response.send_message(f"✅ XP de {usuario.mention} reiniciado.", ephemeral=True)

    @admin.command(name="recompensa-agregar", description="Dar un rol automáticamente al alcanzar un nivel")
    @app_commands.describe(nivel="Nivel requerido", rol="Rol a otorgar")
    async def reward_add(self, interaction: discord.Interaction, nivel: app_commands.Range[int, 1, 500],
                         rol: discord.Role) -> None:
        me = interaction.guild.me if interaction.guild else None
        if rol.managed or rol.is_default() or (me and rol >= me.top_role):
            await interaction.response.send_message("No puedo asignar ese rol (gestionado o por encima del mío).",
                                                    ephemeral=True)
            return
        async with self.bot.db.session() as session:
            await session.execute(insert(LevelReward).values(id=new_id(), guild_id=str(interaction.guild_id), level=nivel,
                                                             role_id=str(rol.id)).on_conflict_do_nothing())
        self._rewards.delete(str(interaction.guild_id))
        await interaction.response.send_message(f"✅ {rol.mention} se otorgará al llegar al **nivel {nivel}**.",
                                                ephemeral=True)

    @admin.command(name="recompensa-quitar", description="Eliminar una recompensa de nivel")
    @app_commands.describe(rol="Rol de la recompensa", nivel="Nivel (vacío = todas las de ese rol)")
    async def reward_remove(self, interaction: discord.Interaction, rol: discord.Role,
                            nivel: app_commands.Range[int, 1, 500] | None = None) -> None:
        query = delete(LevelReward).where(LevelReward.guild_id == str(interaction.guild_id),
                                          LevelReward.role_id == str(rol.id))
        if nivel is not None:
            query = query.where(LevelReward.level == nivel)
        async with self.bot.db.session() as session:
            removed = (await session.execute(query)).rowcount  # type: ignore[attr-defined]
        self._rewards.delete(str(interaction.guild_id))
        await interaction.response.send_message(
            f"✅ {removed} recompensa(s) eliminada(s)." if removed else "No había recompensas con ese rol.", ephemeral=True)

    @admin.command(name="recompensas", description="Ver las recompensas de nivel configuradas")
    async def reward_list(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        rewards = await self._guild_rewards(interaction.guild.id)
        config = await self.bot.configs.get(interaction.guild.id)
        embed = discord.Embed(color=COLOR, title="🏆 Recompensas de nivel", description="\n".join(
            f"Nivel **{r.level}** → <@&{r.role_id}>" for r in rewards) or "_No hay recompensas configuradas._")
        embed.set_footer(text="Las recompensas se acumulan" if config.level_rewards_stack
                         else "Solo se conserva la recompensa más alta")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Leveling(bot))
