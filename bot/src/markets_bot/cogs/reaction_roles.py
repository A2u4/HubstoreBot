"""Reaction roles: role buttons (``rr_<id>``) and emoji reactions on any message."""

from __future__ import annotations

import logging
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from markets_bot.bot import MarketsBot
from markets_bot.core.utils import module_color
from markets_bot.db.models import ReactionRole

log = logging.getLogger(__name__)

TYPE_CHOICES = [
    app_commands.Choice(name="Alternar (dar/quitar)", value="toggle"),
    app_commands.Choice(name="Solo dar", value="give"),
    app_commands.Choice(name="Solo quitar", value="remove"),
]
TYPE_SHORT = {"toggle": "alternar", "give": "dar", "remove": "quitar"}
TYPE_LONG = {"toggle": "alternar (dar/quitar)", "give": "solo dar", "remove": "solo quitar"}


def emoji_key(emoji: discord.PartialEmoji) -> str:
    """How reaction-role emojis are stored: unicode as-is, custom as ``<a:name:id>``."""
    if emoji.id:
        return f"<{'a' if emoji.animated else ''}:{emoji.name}:{emoji.id}>"
    return emoji.name or ""


def build_rows(guild: discord.Guild, roles: list[ReactionRole]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for index, item in enumerate(roles[:25]):
        role = guild.get_role(int(item.role_id))
        button = discord.ui.Button(custom_id=f"rr_{item.id}", label=(role.name if role else "Rol")[:80],
                                   style=discord.ButtonStyle.secondary, row=index // 5)
        if item.emoji:
            try:
                button.emoji = discord.PartialEmoji.from_str(item.emoji)
            except (TypeError, ValueError):
                pass
        view.add_item(button)
    return view


class ReactionRoles(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        bot.router.prefix("button", "rr_", self.on_button)

    # ── Buttons ──────────────────────────────────────────────────────────

    async def on_button(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return
        rr_id = str((interaction.data or {}).get("custom_id", "")).removeprefix("rr_")
        async with self.bot.db.session() as session:
            item = await session.get(ReactionRole, rr_id)
        if item is None:
            await interaction.response.send_message("Este boton de rol ya no esta configurado.", ephemeral=True)
            return
        role = guild.get_role(int(item.role_id))
        if role is None:
            await interaction.response.send_message("El rol configurado ya no existe.", ephemeral=True)
            return
        if role >= guild.me.top_role:
            await interaction.response.send_message(
                "No puedo asignar este rol (esta por encima de mi rol mas alto).", ephemeral=True)
            return
        has = member.get_role(role.id) is not None
        try:
            if item.type == "give":
                if has:
                    text = f"Ya tienes el rol **{role.name}**."
                else:
                    await member.add_roles(role)
                    text = f"Se te asigno el rol **{role.name}**."
            elif item.type == "remove":
                if has:
                    await member.remove_roles(role)
                    text = f"Se removio el rol **{role.name}**."
                else:
                    text = f"No tienes el rol **{role.name}**."
            elif has:
                await member.remove_roles(role)
                text = f"Se removio el rol **{role.name}**."
            else:
                await member.add_roles(role)
                text = f"Se agrego el rol **{role.name}**."
        except discord.HTTPException:
            log.exception("Error toggling reaction role")
            text = "No se pudieron actualizar tus roles. Intenta de nuevo."
        await interaction.response.send_message(text, ephemeral=True)

    # ── Emoji reactions ──────────────────────────────────────────────────

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, added: bool) -> None:
        if payload.guild_id is None or (payload.member and payload.member.bot):
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        async with self.bot.db.session() as session:
            item = (await session.execute(select(ReactionRole).where(
                ReactionRole.message_id == str(payload.message_id),
                ReactionRole.emoji == emoji_key(payload.emoji),
            ))).scalar_one_or_none()
        if item is None:
            return
        member = guild.get_member(payload.user_id)
        role = guild.get_role(int(item.role_id))
        if member is None or member.bot or role is None or role >= guild.me.top_role:
            return
        try:
            if added:
                if item.type == "remove":
                    await member.remove_roles(role)
                else:
                    await member.add_roles(role)
            elif item.type in ("toggle", "give"):
                await member.remove_roles(role)
        except discord.HTTPException as exc:
            log.error("Error handling emoji reaction role: %s", exc)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload, True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload, False)

    # ── /rolreaccion ─────────────────────────────────────────────────────

    rolreaccion = app_commands.Group(
        name="rolreaccion", description="Gestionar roles por botones de reacción", guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
        extras={"module": "moderation", "cooldown": 5, "permissions": ["manage_roles"]},
    )

    async def _refresh_panel(self, guild: discord.Guild, channel_id: str, message_id: str) -> None:
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            return
        async with self.bot.db.session() as session:
            items = list((await session.execute(select(ReactionRole).where(
                ReactionRole.guild_id == str(guild.id), ReactionRole.message_id == message_id,
            ))).scalars().all())
        message = await channel.fetch_message(int(message_id))
        await message.edit(view=build_rows(guild, items) if items else None)

    @rolreaccion.command(name="crear", description="Crear un panel de roles por reacción")
    @app_commands.describe(titulo="Título del panel", descripcion="Descripción del panel")
    async def create(self, interaction: discord.Interaction, titulo: str, descripcion: str | None = None) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("No se pueden enviar mensajes en este canal.", ephemeral=True)
            return
        embed = discord.Embed(color=module_color("moderation"), title=titulo,
                              description=descripcion or "Haz clic en un botón para obtener un rol.")
        embed.set_footer(text="Usa /rolreaccion agregar para añadir botones de rol a este mensaje")
        message = await channel.send(embed=embed)
        await interaction.response.send_message(
            f"Panel de roles por reacción creado. ID del mensaje: `{message.id}`\n"
            f"Usa `/rolreaccion agregar id_mensaje:{message.id} rol:@rol` para añadir botones.", ephemeral=True)

    @rolreaccion.command(name="agregar", description="Agregar un botón de rol a un panel")
    @app_commands.describe(id_mensaje="ID del mensaje del panel", rol="Rol a asignar", etiqueta="Etiqueta del botón",
                           emoji="Emoji del botón", tipo="Tipo de comportamiento")
    @app_commands.choices(tipo=TYPE_CHOICES)
    async def add(self, interaction: discord.Interaction, id_mensaje: str, rol: discord.Role,
                  etiqueta: str | None = None, emoji: str | None = None, tipo: str = "toggle") -> None:
        # `etiqueta` is accepted for compatibility; buttons always show the role name (as in v1).
        guild = interaction.guild
        channel = interaction.channel
        assert guild is not None
        if not isinstance(channel, discord.abc.Messageable) or not id_mensaje.isdigit():
            await interaction.response.send_message("Mensaje no encontrado en este canal.", ephemeral=True)
            return
        try:
            message = await channel.fetch_message(int(id_mensaje))
        except discord.HTTPException:
            await interaction.response.send_message("Mensaje no encontrado en este canal.", ephemeral=True)
            return
        if message.author.id != guild.me.id:
            await interaction.response.send_message("Solo puedo añadir botones a mis propios mensajes.", ephemeral=True)
            return
        item = ReactionRole(guild_id=str(guild.id), channel_id=str(channel.id), message_id=id_mensaje,  # type: ignore[union-attr]
                            emoji=emoji or "🔹", role_id=str(rol.id), type=tipo)
        async with self.bot.db.session() as session:
            session.add(item)
        await self._refresh_panel(guild, str(channel.id), id_mensaje)  # type: ignore[union-attr]
        await interaction.response.send_message(
            f"Se añadió el botón de **{rol.name}** al panel. ID: `{item.id[:8]}`", ephemeral=True)

    @rolreaccion.command(name="eliminar", description="Eliminar un botón de rol de un panel")
    @app_commands.describe(id="ID del rol de reacción")
    async def remove(self, interaction: discord.Interaction, id: str) -> None:
        guild = interaction.guild
        assert guild is not None
        async with self.bot.db.session() as session:
            item = (await session.execute(select(ReactionRole).where(
                ReactionRole.guild_id == str(guild.id), ReactionRole.id.startswith(id)).limit(1)
            )).scalar_one_or_none()
            if item is None:
                await interaction.response.send_message("Rol de reacción no encontrado.", ephemeral=True)
                return
            await session.execute(delete(ReactionRole).where(ReactionRole.id == item.id))
        try:
            await self._refresh_panel(guild, item.channel_id, item.message_id)
        except discord.HTTPException:
            pass  # message may have been deleted
        await interaction.response.send_message("Rol de reacción eliminado.", ephemeral=True)

    @rolreaccion.command(name="emoji", description="Dar un rol cuando alguien reaccione con un emoji en cualquier mensaje")
    @app_commands.describe(id_mensaje="ID del mensaje", rol="Rol a asignar", emoji="Emoji de reacción (ej. ✅)",
                           tipo="Comportamiento")
    @app_commands.choices(tipo=TYPE_CHOICES)
    async def emoji(self, interaction: discord.Interaction, id_mensaje: str, rol: discord.Role, emoji: str,
                    tipo: str = "toggle") -> None:
        guild = interaction.guild
        channel = interaction.channel
        assert guild is not None and channel is not None
        try:
            await channel.fetch_message(int(id_mensaje))  # type: ignore[union-attr]
        except (ValueError, discord.HTTPException):
            await interaction.response.send_message("Mensaje no encontrado en este canal.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            stmt = insert(ReactionRole).values(guild_id=str(guild.id), channel_id=str(channel.id),
                                               message_id=id_mensaje, emoji=emoji, role_id=str(rol.id), type=tipo)
            await session.execute(stmt.on_conflict_do_update(
                index_elements=["messageId", "emoji"],
                set_={"roleId": str(rol.id), "type": tipo, "channelId": str(channel.id)}))
        await interaction.response.send_message(
            f"Listo. Cuando alguien reaccione con {emoji} en ese mensaje, se le {TYPE_LONG[tipo]} el rol **{rol.name}**.",
            ephemeral=True)

    @rolreaccion.command(name="lista", description="Listar todos los paneles de roles por reacción")
    async def list_(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            items = (await session.execute(
                select(ReactionRole).where(ReactionRole.guild_id == str(interaction.guild_id))
            )).scalars().all()
        if not items:
            await interaction.response.send_message("No hay roles de reacción configurados.", ephemeral=True)
            return
        grouped: dict[str, list[ReactionRole]] = defaultdict(list)
        for item in items:
            grouped[item.message_id].append(item)
        lines = []
        for message_id, roles in grouped.items():
            lines.append(f"**Mensaje:** `{message_id}` en <#{roles[0].channel_id}>")
            lines.extend(f"  {r.emoji} <@&{r.role_id}> ({TYPE_SHORT.get(r.type, r.type)}) — `{r.id[:8]}`" for r in roles)
            lines.append("")
        embed = discord.Embed(color=module_color("moderation"), title="Roles de Reacción",
                              description="\n".join(lines)[:4096], timestamp=discord.utils.utcnow())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(ReactionRoles(bot))
