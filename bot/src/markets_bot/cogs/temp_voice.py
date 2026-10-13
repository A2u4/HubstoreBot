"""Join-to-create voice channels (VoiceMaster style) with owner controls under ``/voz``."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select, update

from markets_bot.bot import MarketsBot
from markets_bot.core.errors import UserError
from markets_bot.core.utils import render_template
from markets_bot.db.models import GuildConfig, TempVoiceChannel

log = logging.getLogger(__name__)


class TempVoice(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self.owners: dict[int, int] = {}  # channel id -> owner id (mirror of temp_voice_channels)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Load this bot's temp channels and clean up the ones emptied or deleted while offline."""
        guild_ids = [str(g.id) for g in self.bot.guilds]
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(TempVoiceChannel).where(
                TempVoiceChannel.guild_id.in_(guild_ids)))).scalars().all()
        for row in rows:
            channel = self.bot.get_channel(int(row.channel_id))
            self.owners[int(row.channel_id)] = int(row.owner_id)
            if not isinstance(channel, discord.VoiceChannel):
                await self._forget(int(row.channel_id))
            elif not channel.members:
                await self._delete(channel)

    async def _forget(self, channel_id: int) -> None:
        self.owners.pop(channel_id, None)
        async with self.bot.db.session() as session:
            await session.execute(delete(TempVoiceChannel).where(TempVoiceChannel.channel_id == str(channel_id)))

    async def _delete(self, channel: discord.VoiceChannel) -> None:
        try:
            await channel.delete(reason="Canal temporal vacío")
        except discord.NotFound:
            pass
        except discord.HTTPException as exc:
            log.warning("temp voice: could not delete %s: %s", channel.id, exc)
            return
        await self._forget(channel.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState) -> None:
        if before.channel == after.channel:
            return
        left = before.channel
        if isinstance(left, discord.VoiceChannel) and left.id in self.owners and not left.members:
            await self._delete(left)
        if after.channel is None or member.bot:
            return
        config = await self.bot.configs.get(member.guild.id)
        if config.temp_voice_enabled and str(after.channel.id) == config.temp_voice_hub_channel_id:
            await self._create_for(member, after.channel, config)

    async def _create_for(self, member: discord.Member, hub: discord.abc.GuildChannel, config: GuildConfig) -> None:
        guild = member.guild
        existing = next((cid for cid, owner in self.owners.items() if owner == member.id and guild.get_channel(cid)), None)
        if existing:  # one channel per member: send them back to it
            channel = guild.get_channel(existing)
            if isinstance(channel, discord.VoiceChannel):
                await member.move_to(channel)
                return
        category_id = config.temp_voice_category_id or ""
        category = guild.get_channel(int(category_id)) if category_id.isdigit() else hub.category
        name = render_template(config.temp_voice_name_template or "🔊 {user}", {
            "user": member.display_name, "username": member.name})[:100]
        overwrites = dict(category.overwrites) if isinstance(category, discord.CategoryChannel) else {}
        overwrites[member] = discord.PermissionOverwrite(connect=True, speak=True, manage_channels=True,
                                                         move_members=True, mute_members=True)
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True,
                                                               view_channel=True)
        try:
            channel = await guild.create_voice_channel(
                name, category=category if isinstance(category, discord.CategoryChannel) else None,
                user_limit=max(0, min(99, config.temp_voice_user_limit or 0)),
                overwrites=overwrites, reason=f"Canal temporal de {member}")
        except discord.HTTPException as exc:
            log.error("temp voice: could not create channel in %s: %s", guild.id, exc)
            return
        self.owners[channel.id] = member.id
        async with self.bot.db.session() as session:
            session.add(TempVoiceChannel(guild_id=str(guild.id), channel_id=str(channel.id), owner_id=str(member.id)))
        try:
            await member.move_to(channel)
        except discord.HTTPException:
            await self._delete(channel)  # they left before we could move them

    # ── /voz (owner controls) ────────────────────────────────────────────

    group = app_commands.Group(name="voz", description="Controlar tu canal de voz temporal", guild_only=True,
                               extras={"module": "tempvoice", "cooldown": 3, "public": True})

    def _owned(self, interaction: discord.Interaction, *, allow_claim: bool = False) -> discord.VoiceChannel:
        member = interaction.user
        channel = member.voice.channel if isinstance(member, discord.Member) and member.voice else None
        if not isinstance(channel, discord.VoiceChannel) or channel.id not in self.owners:
            raise UserError("Debes estar en un canal de voz temporal.")
        if self.owners[channel.id] != member.id and not allow_claim:
            raise UserError("Solo el dueño del canal puede hacer eso. Si se fue, usa `/voz reclamar`.")
        return channel

    async def _set_owner(self, channel: discord.VoiceChannel, old: int, new: discord.Member) -> None:
        self.owners[channel.id] = new.id
        old_member = channel.guild.get_member(old)
        if old_member:
            await channel.set_permissions(old_member, overwrite=None)
        await channel.set_permissions(new, connect=True, speak=True, manage_channels=True, move_members=True,
                                      mute_members=True)
        async with self.bot.db.session() as session:
            await session.execute(update(TempVoiceChannel).where(TempVoiceChannel.channel_id == str(channel.id))
                                  .values(owner_id=str(new.id)))

    @group.command(name="nombre", description="Renombrar tu canal")
    @app_commands.describe(nombre="Nuevo nombre")
    async def rename(self, interaction: discord.Interaction, nombre: app_commands.Range[str, 1, 100]) -> None:
        channel = self._owned(interaction)
        await channel.edit(name=nombre)
        await interaction.response.send_message(f"✅ Canal renombrado a **{nombre}**.", ephemeral=True)

    @group.command(name="limite", description="Cambiar el límite de usuarios (0 = sin límite)")
    @app_commands.describe(cantidad="Límite de usuarios")
    async def limit(self, interaction: discord.Interaction, cantidad: app_commands.Range[int, 0, 99]) -> None:
        channel = self._owned(interaction)
        await channel.edit(user_limit=cantidad)
        await interaction.response.send_message(f"✅ Límite: **{cantidad or 'sin límite'}**.", ephemeral=True)

    @group.command(name="bloquear", description="Impedir que otros entren a tu canal")
    async def lock(self, interaction: discord.Interaction) -> None:
        channel = self._owned(interaction)
        await channel.set_permissions(channel.guild.default_role, connect=False)
        await interaction.response.send_message("🔒 Canal bloqueado.", ephemeral=True)

    @group.command(name="desbloquear", description="Permitir que cualquiera entre a tu canal")
    async def unlock(self, interaction: discord.Interaction) -> None:
        channel = self._owned(interaction)
        await channel.set_permissions(channel.guild.default_role, connect=None)
        await interaction.response.send_message("🔓 Canal desbloqueado.", ephemeral=True)

    @group.command(name="ocultar", description="Ocultar tu canal de la lista")
    async def hide(self, interaction: discord.Interaction) -> None:
        channel = self._owned(interaction)
        await channel.set_permissions(channel.guild.default_role, view_channel=False)
        await interaction.response.send_message("🙈 Canal oculto.", ephemeral=True)

    @group.command(name="mostrar", description="Volver a mostrar tu canal")
    async def show(self, interaction: discord.Interaction) -> None:
        channel = self._owned(interaction)
        await channel.set_permissions(channel.guild.default_role, view_channel=None)
        await interaction.response.send_message("👀 Canal visible.", ephemeral=True)

    @group.command(name="permitir", description="Dejar entrar a alguien aunque el canal esté bloqueado")
    @app_commands.describe(usuario="Miembro")
    async def permit(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        channel = self._owned(interaction)
        await channel.set_permissions(usuario, connect=True, view_channel=True)
        await interaction.response.send_message(f"✅ {usuario.mention} puede entrar.", ephemeral=True)

    @group.command(name="expulsar", description="Sacar a alguien de tu canal y bloquearle la entrada")
    @app_commands.describe(usuario="Miembro")
    async def kick(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        channel = self._owned(interaction)
        if usuario.id == interaction.user.id:
            raise UserError("No puedes expulsarte a ti mismo.")
        await channel.set_permissions(usuario, connect=False)
        if usuario.voice and usuario.voice.channel == channel:
            await usuario.move_to(None)
        await interaction.response.send_message(f"👢 {usuario.mention} fue expulsado del canal.", ephemeral=True)

    @group.command(name="transferir", description="Dar la propiedad del canal a otro miembro")
    @app_commands.describe(usuario="Nuevo dueño (debe estar en el canal)")
    async def transfer(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        channel = self._owned(interaction)
        if usuario not in channel.members or usuario.bot:
            raise UserError("El nuevo dueño debe estar en el canal.")
        await self._set_owner(channel, interaction.user.id, usuario)
        await interaction.response.send_message(f"👑 {usuario.mention} ahora es dueño del canal.")

    @group.command(name="reclamar", description="Reclamar el canal si su dueño se fue")
    async def claim(self, interaction: discord.Interaction) -> None:
        channel = self._owned(interaction, allow_claim=True)
        owner = self.owners[channel.id]
        if owner == interaction.user.id:
            raise UserError("Ya eres el dueño de este canal.")
        if any(m.id == owner for m in channel.members):
            raise UserError("El dueño sigue en el canal.")
        assert isinstance(interaction.user, discord.Member)
        await self._set_owner(channel, owner, interaction.user)
        await interaction.response.send_message(f"👑 {interaction.user.mention} reclamó el canal.")


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(TempVoice(bot))
