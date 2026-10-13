"""Staff tools: /dinero-rangos (rank sales counter), /dar-rango and the "Estoy interesado" button."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, update

from markets_bot.bot import MarketsBot
from markets_bot.core.utils import OK, discord_ts, utcnow
from markets_bot.db.models import GuildConfig, RankMoneyEntry
from markets_bot.services.tickets.manager import archive_rank_images

log = logging.getLogger(__name__)

MONEY_COLOR = 0xF1C40F
RANKS = {"shopper": ("Shopper", 250_000), "access": ("Access", 500_000), "vip": ("VIP", 1_000_000)}

DEFAULT_ACCESS_MSG = ("¡Felicidades! 🎉\n\nAhora tienes el rango **{rol}**.\n\nYa puedes hacer tus **publicaciones OOC** "
                      "en los canales correspondientes.")
DEFAULT_VIP_MSG = ("¡Felicidades! ⭐\n\nAhora tienes el rango **{rol}**.\n\nYa puedes acceder a los **canales VIP** "
                   "exclusivos y usar el **@everyone moderadamente**.")
DEFAULT_MSG = "¡Felicidades! 🎉\n\nSe te ha asignado el rango **{rol}**.\n\nDisfruta de tus nuevos privilegios."

INTEREST_PREFIX = "interest_create_"  # suffix is the category id the channel is created in


def money(value: int) -> str:
    if value >= 1_000_000:
        return f"{value // 1_000_000}M IC" if value % 1_000_000 == 0 else f"{value / 1_000_000:.2f}M IC"
    if value >= 1_000 and value % 1_000 == 0:
        return f"{value // 1_000}K IC"
    return f"{value:,} IC".replace(",", ".")


def summarize(entries: list[RankMoneyEntry]) -> dict[str, int]:
    summary = {"total": 0, "adrian": 0, "keng": 0, "shopper": 0, "access": 0, "vip": 0}
    for entry in entries:
        summary["total"] += entry.amount
        summary["adrian"] += entry.adrian_share
        summary["keng"] += entry.keng_share
        if entry.rank_type in summary:
            summary[entry.rank_type] += 1
    return summary


def _rank_entry(role_name: str, config: GuildConfig) -> dict[str, Any] | None:
    name = role_name.lower()
    return next((e for e in config.dar_rango_roles or []
                 if isinstance(e, dict) and e.get("pattern") and str(e["pattern"]).lower() in name), None)


def rank_message(role_name: str, user_id: int, config: GuildConfig) -> str:
    entry = _rank_entry(role_name, config)
    if entry and entry.get("message"):
        template = str(entry["message"])
    elif "access" in role_name.lower():
        template = DEFAULT_ACCESS_MSG
    elif "vip" in role_name.lower():
        template = DEFAULT_VIP_MSG
    else:
        template = DEFAULT_MSG
    return f"<@{user_id}> " + template.replace("{rol}", role_name)


def _is_staff(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.manage_roles or perms.manage_guild or perms.administrator


class StaffTools(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        bot.router.prefix("button", INTEREST_PREFIX, self.on_interest_button)

    # ── /dinero-rangos ───────────────────────────────────────────────────

    money_group = app_commands.Group(
        name="dinero-rangos", description="Contador staff del dinero de rangos Shopper/Access/VIP", guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
        extras={"module": "moderation", "cooldown": 2, "permissions": ["manage_roles"]})

    async def _pending(self, guild_id: int) -> list[RankMoneyEntry]:
        async with self.bot.db.session() as session:
            return list((await session.execute(select(RankMoneyEntry).where(
                RankMoneyEntry.guild_id == str(guild_id), RankMoneyEntry.withdrawn_at.is_(None))
                .order_by(RankMoneyEntry.created_at.desc()))).scalars())

    async def _staff_only(self, interaction: discord.Interaction) -> bool:
        if isinstance(interaction.user, discord.Member) and _is_staff(interaction.user):
            return True
        await interaction.response.send_message("Solo el staff puede usar este contador.", ephemeral=True)
        return False

    @money_group.command(name="registrar", description="Registrar una venta de Shopper, Access o VIP")
    @app_commands.describe(rango="Rango vendido", usuario="Usuario que compro el rango", nota="Nota opcional del pago")
    @app_commands.choices(rango=[app_commands.Choice(name=f"{label} - {money(amount).removesuffix(' IC')} IC", value=key)
                                 for key, (label, amount) in RANKS.items()])
    async def money_register(self, interaction: discord.Interaction, rango: str, usuario: discord.User | None = None,
                             nota: app_commands.Range[str, 1, 200] | None = None) -> None:
        if not await self._staff_only(interaction):
            return
        label, amount = RANKS[rango]
        adrian = amount // 2
        entry = RankMoneyEntry(guild_id=str(interaction.guild_id), rank_type=rango, amount=amount, adrian_share=adrian,
                               keng_share=amount - adrian, buyer_id=str(usuario.id) if usuario else None,
                               recorded_by_id=str(interaction.user.id), note=nota)
        async with self.bot.db.session() as session:
            session.add(entry)
        summary = summarize(await self._pending(interaction.guild_id or 0))
        embed = discord.Embed(color=MONEY_COLOR, title="💰 Dinero de rangos registrado",
                              description=f"Se registro **{label}** por **{money(amount)}**.",
                              timestamp=discord.utils.utcnow())
        for name, value in (("Usuario", usuario.mention if usuario else "No indicado"), ("Adrian", money(adrian)),
                            ("Keng", money(amount - adrian)), ("Pendiente total", money(summary["total"])),
                            ("Pendiente Adrian", money(summary["adrian"])), ("Pendiente Keng", money(summary["keng"]))):
            embed.add_field(name=name, value=value, inline=True)
        if nota:
            embed.add_field(name="Nota", value=nota, inline=False)
        embed.set_footer(text=f"ID registro: {entry.id[:8]}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @money_group.command(name="ver", description="Ver el dinero pendiente para Adrian y Keng")
    async def money_view(self, interaction: discord.Interaction) -> None:
        if not await self._staff_only(interaction):
            return
        entries = await self._pending(interaction.guild_id or 0)
        summary = summarize(entries)
        embed = discord.Embed(color=MONEY_COLOR, title="💰 Contador pendiente de rangos", timestamp=discord.utils.utcnow(),
                              description="División 50% / 50% de ventas Shopper, Access y VIP." if entries
                              else "No hay dinero pendiente por retirar.")
        for name, value in (("Shopper registrados", str(summary["shopper"])), ("Access registrados", str(summary["access"])),
                            ("VIP registrados", str(summary["vip"])), ("Total pendiente", money(summary["total"])),
                            ("Para Adrian", money(summary["adrian"])), ("Para Keng", money(summary["keng"]))):
            embed.add_field(name=name, value=value, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @money_group.command(name="historial", description="Ver los ultimos registros del contador")
    @app_commands.rename(include_withdrawn="incluye-retirados")
    @app_commands.describe(include_withdrawn="Mostrar tambien registros ya retirados")
    async def money_history(self, interaction: discord.Interaction, include_withdrawn: bool = False) -> None:
        if not await self._staff_only(interaction):
            return
        query = select(RankMoneyEntry).where(RankMoneyEntry.guild_id == str(interaction.guild_id))
        if not include_withdrawn:
            query = query.where(RankMoneyEntry.withdrawn_at.is_(None))
        async with self.bot.db.session() as session:
            entries = (await session.execute(query.order_by(RankMoneyEntry.created_at.desc()).limit(15))).scalars().all()
        lines = [f"**{i}.** {RANKS.get(e.rank_type, (e.rank_type,))[0]} - {money(e.amount)} - "
                 f"{f'<@{e.buyer_id}>' if e.buyer_id else 'Sin usuario'} - "
                 f"{'Retirado' if e.withdrawn_at else 'Pendiente'} - {discord_ts(e.created_at)}"
                 for i, e in enumerate(entries, 1)]
        await interaction.response.send_message(ephemeral=True, embed=discord.Embed(
            color=MONEY_COLOR, title="💰 Historial de dinero de rangos", timestamp=discord.utils.utcnow(),
            description="\n".join(lines) or "No hay registros para mostrar."))

    @money_group.command(name="reset", description="Resetear el contador pendiente cuando se retire el dinero")
    @app_commands.describe(nota="Nota del retiro")
    async def money_reset(self, interaction: discord.Interaction,
                          nota: app_commands.Range[str, 1, 200] | None = None) -> None:
        if not await self._staff_only(interaction):
            return
        gid = str(interaction.guild_id)
        async with self.bot.db.session() as session:
            # Mark exactly the rows we summarize, so a sale registered mid-reset is never lost.
            entries = list((await session.execute(select(RankMoneyEntry).where(
                RankMoneyEntry.guild_id == gid, RankMoneyEntry.withdrawn_at.is_(None)).with_for_update())).scalars())
            if entries:
                await session.execute(update(RankMoneyEntry).where(RankMoneyEntry.id.in_([e.id for e in entries]))
                                      .values(withdrawn_at=utcnow(), withdrawn_by_id=str(interaction.user.id),
                                              withdrawal_note=nota))
        if not entries:
            await interaction.response.send_message("No hay dinero pendiente para resetear.", ephemeral=True)
            return
        summary = summarize(entries)
        embed = discord.Embed(color=MONEY_COLOR, title="💰 Contador reseteado",
                              description="Se marco el dinero pendiente como retirado.", timestamp=discord.utils.utcnow())
        for name, value in (("Registros retirados", str(len(entries))), ("Total retirado", money(summary["total"])),
                            ("Adrian", money(summary["adrian"])), ("Keng", money(summary["keng"]))):
            embed.add_field(name=name, value=value, inline=True)
        if nota:
            embed.add_field(name="Nota del retiro", value=nota, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /dar-rango ───────────────────────────────────────────────────────

    @app_commands.command(name="dar-rango", description="Asigna un rango/rol a un usuario y registra la transcripción",
                          extras={"module": "moderation", "permissions": ["manage_roles"]})
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    @app_commands.rename(send_dm="enviar-dm")
    @app_commands.describe(usuario="Usuario al que asignar el rango", rol="Rol a asignar",
                           anunciar="¿Mostrar anuncio público en este canal mencionando al usuario?",
                           send_dm="¿Enviar mensaje privado (DM) al usuario? (por defecto: Sí)")
    async def give_rank(self, interaction: discord.Interaction, usuario: discord.Member, rol: discord.Role,
                        anunciar: bool = False, send_dm: bool = True) -> None:
        guild = interaction.guild
        assert guild is not None
        await interaction.response.defer(ephemeral=True)
        config = await self.bot.configs.get(guild.id)
        color = rol.color.value or OK
        try:
            await usuario.add_roles(rol, reason=f"Rango dado por {interaction.user.name}")
        except discord.HTTPException as exc:
            log.error("dar-rango: could not add role %s: %s", rol.id, exc)
            await interaction.followup.send("No tengo permisos para asignar ese rol.", ephemeral=True)
            return

        message = rank_message(rol.name, usuario.id, config)
        if send_dm:
            dm = discord.Embed(color=color, title=f"🎖️ ¡Nuevo rango en {guild.name}!", description=message,
                               timestamp=discord.utils.utcnow())
            if guild.icon:
                dm.set_thumbnail(url=guild.icon.with_size(128).url)
            try:
                await usuario.send(embed=dm)
            except discord.HTTPException:
                log.info("dar-rango: DMs closed for %s", usuario.id)

        confirm = discord.Embed(color=color, title="🎖️ Rango asignado", timestamp=discord.utils.utcnow(),
                                description=f"{usuario.mention} ha recibido el rango **{rol.name}** correctamente.")
        for name, value in (("Usuario", usuario.name), ("ID", str(usuario.id)), ("Rango", rol.mention),
                            ("Asignado por", interaction.user.name)):
            confirm.add_field(name=name, value=value, inline=True)
        confirm.set_thumbnail(url=usuario.display_avatar.url)
        await interaction.followup.send(embed=confirm, ephemeral=True)

        channel = interaction.channel
        if anunciar and isinstance(channel, discord.abc.Messageable):
            announce = discord.Embed(color=color, title="🎖️ ¡Nuevo rango asignado!", timestamp=discord.utils.utcnow(),
                                     description=f"{usuario.mention} ha recibido el rango {rol.mention}.\n\n{message}")
            announce.set_thumbnail(url=usuario.display_avatar.url)
            try:
                await channel.send(embed=announce)
            except discord.HTTPException:
                pass

        # darRangoImagesChannelId, falling back to the legacy verification log channel.
        target_id = config.dar_rango_images_channel_id or config.verification_log_channel_id
        log_channel = guild.get_channel(int(target_id)) if target_id and target_id.isdigit() else None
        if not isinstance(log_channel, discord.TextChannel) or not isinstance(channel, discord.TextChannel):
            if target_id:
                log.warning("dar-rango: archive channel %s not found in %s", target_id, guild.id)
            return
        try:
            await archive_rank_images(channel, log_channel, str(usuario.id), role_name=rol.name, color=color,
                                      assigned_by=interaction.user.name)
        except Exception:
            log.exception("dar-rango: failed to archive ticket images")

    # ── "Estoy interesado" button → private interest channel ─────────────

    async def on_interest_button(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Solo disponible en un servidor.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        marker = f"userId:{user.id}"
        existing = next((c for c in guild.text_channels if c.name.startswith("interes-") and c.topic
                         and marker in c.topic), None)
        if existing:
            await interaction.followup.send(f"Ya tienes un canal de interés abierto: {existing.mention}", ephemeral=True)
            return

        config = await self.bot.configs.get(guild.id)
        staff_roles = [r for rid in config.ticket_staff_role_ids or [] if (r := guild.get_role(int(rid)))]
        custom_id = str((interaction.data or {}).get("custom_id", ""))
        category_id = custom_id.removeprefix(INTEREST_PREFIX)
        category = guild.get_channel(int(category_id)) if category_id.isdigit() else None
        access = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        overwrites: dict[Any, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False), user: access,
            **{role: access for role in staff_roles}}
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        try:
            channel = await guild.create_text_channel(
                f"interes-{user.name}", topic=marker, overwrites=overwrites,
                category=category if isinstance(category, discord.CategoryChannel) else None)
        except discord.HTTPException as exc:
            log.error("interest: failed to create channel: %s", exc)
            await interaction.followup.send("No se pudo crear el canal. Contacta a un administrador.", ephemeral=True)
            return

        welcome = discord.Embed(color=0x5865F2, title="Solicitud de interés", timestamp=discord.utils.utcnow(),
                                description=f"{user.mention}, gracias por tu interés. Por favor describe en qué "
                                            "publicación estás interesado y el equipo te atenderá pronto.")
        try:
            await channel.send(content=" ".join(r.mention for r in staff_roles) or None, embed=welcome,
                               allowed_mentions=discord.AllowedMentions(roles=staff_roles))
        except discord.HTTPException:
            pass
        await interaction.followup.send(f"✅ Se ha creado tu canal de interés: {channel.mention}", ephemeral=True)
        log.info("interest: created %s for %s", channel.name, user.id)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(StaffTools(bot))
