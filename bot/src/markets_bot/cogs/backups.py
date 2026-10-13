"""Server backups (``/respaldo``): roles, categories and channels serialized to JSON.

The JSON shape matches v1 so existing backups stay restorable.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select

from markets_bot.bot import MarketsBot
from markets_bot.core.utils import ERROR, discord_ts, module_color
from markets_bot.db.models import Backup

log = logging.getLogger(__name__)

TEXT_TYPES = (discord.ChannelType.text, discord.ChannelType.news)
VOICE_TYPES = (discord.ChannelType.voice, discord.ChannelType.stage_voice)


def _overwrites(channel: discord.abc.GuildChannel) -> list[dict[str, Any]]:
    """Role/member overwrites (the @everyone overwrite is skipped, as in v1)."""
    result = []
    for target, overwrite in channel.overwrites.items():
        if target.id == channel.guild.id:
            continue
        allow, deny = overwrite.pair()
        result.append({"type": 0 if isinstance(target, discord.Role) else 1,
                       "roleName": target.name if isinstance(target, discord.Role) else None,
                       "allow": str(allow.value), "deny": str(deny.value)})
    return result


def create_backup_data(guild: discord.Guild) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": guild.name,
        "icon": guild.icon.with_size(1024).url if guild.icon else None,
        "verificationLevel": guild.verification_level.value,
        "defaultMessageNotifications": guild.default_notifications.value,
        "explicitContentFilter": guild.explicit_content_filter.value,
        "afkChannelId": str(guild.afk_channel.id) if guild.afk_channel else None,
        "afkTimeout": guild.afk_timeout,
        "systemChannelId": str(guild.system_channel.id) if guild.system_channel else None,
    }
    data["roles"] = [
        {"name": r.name, "color": str(r.color), "hoist": r.hoist, "permissions": str(r.permissions.value),
         "mentionable": r.mentionable, "position": r.position}
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default() and not r.managed
    ]
    data["categories"] = [{"name": c.name, "position": c.position, "permissionOverwrites": _overwrites(c)}
                          for c in sorted(guild.categories, key=lambda c: c.position)]
    data["textChannels"] = [
        {"name": c.name, "topic": c.topic, "nsfw": c.nsfw, "rateLimitPerUser": c.slowmode_delay, "position": c.position,
         "parentName": c.category.name if c.category else None, "type": c.type.value, "permissionOverwrites": _overwrites(c)}
        for c in sorted((c for c in guild.channels if c.type in TEXT_TYPES), key=lambda c: c.position)
        if isinstance(c, discord.TextChannel)
    ]
    data["voiceChannels"] = [
        {"name": c.name, "bitrate": c.bitrate, "userLimit": c.user_limit, "position": c.position,
         "parentName": c.category.name if c.category else None, "type": c.type.value, "permissionOverwrites": _overwrites(c)}
        for c in sorted((c for c in guild.channels if c.type in VOICE_TYPES), key=lambda c: c.position)
        if isinstance(c, (discord.VoiceChannel, discord.StageChannel))
    ]
    return data


def _restore_overwrites(guild: discord.Guild, roles: dict[str, discord.Role],
                        saved: list[dict[str, Any]]) -> dict[discord.Role, discord.PermissionOverwrite]:
    result: dict[discord.Role, discord.PermissionOverwrite] = {}
    for item in saved or []:
        role = roles.get(item.get("roleName") or "") or discord.utils.get(guild.roles, name=item.get("roleName"))
        if role is None:
            continue
        allow = discord.Permissions(int(item.get("allow") or 0))
        deny = discord.Permissions(int(item.get("deny") or 0))
        result[role] = discord.PermissionOverwrite.from_pair(allow, deny)
    return result


async def restore_backup_data(guild: discord.Guild, data: dict[str, Any], clear_existing: bool) -> tuple[bool, list[str]]:
    details: list[str] = []
    try:
        if clear_existing:
            for channel in list(guild.channels):
                try:
                    await channel.delete(reason="Backup restore: clearing channels")
                except discord.HTTPException:
                    details.append(f"No se pudo eliminar el canal: {channel.name}")
            for role in list(guild.roles):
                if not role.is_default() and not role.managed:
                    try:
                        await role.delete(reason="Backup restore: clearing roles")
                    except discord.HTTPException:
                        details.append(f"No se pudo eliminar el rol: {role.name}")
            details.append("Se limpiaron los canales y roles existentes")

        roles: dict[str, discord.Role] = {}
        for item in reversed(data.get("roles") or []):
            try:
                color = item.get("color")
                role = await guild.create_role(
                    name=item["name"], hoist=bool(item.get("hoist")), mentionable=bool(item.get("mentionable")),
                    permissions=discord.Permissions(int(item.get("permissions") or 0)), reason="Backup restore",
                    colour=discord.Colour.from_str(color) if color and color != "#000000" else discord.Colour.default())
                roles[item["name"]] = role
                details.append(f"Rol creado: {item['name']}")
            except (discord.HTTPException, ValueError) as exc:
                details.append(f"Error al crear el rol {item.get('name')}: {exc}")

        categories: dict[str, discord.CategoryChannel] = {}
        for item in data.get("categories") or []:
            try:
                category = await guild.create_category(
                    item["name"], overwrites=_restore_overwrites(guild, roles, item.get("permissionOverwrites")),  # type: ignore[arg-type]
                    reason="Backup restore")
                categories[item["name"]] = category
                details.append(f"Categoria creada: {item['name']}")
            except discord.HTTPException as exc:
                details.append(f"Error al crear la categoria {item.get('name')}: {exc}")

        for item in data.get("textChannels") or []:
            try:
                kwargs: dict[str, Any] = {
                    "category": categories.get(item.get("parentName") or ""), "topic": item.get("topic") or None,
                    "nsfw": bool(item.get("nsfw")), "slowmode_delay": int(item.get("rateLimitPerUser") or 0),
                    "overwrites": _restore_overwrites(guild, roles, item.get("permissionOverwrites")),
                    "reason": "Backup restore",
                }
                if item.get("type") == discord.ChannelType.news.value:
                    kwargs["news"] = True
                await guild.create_text_channel(item["name"], **kwargs)
                details.append(f"Canal de texto creado: #{item['name']}")
            except discord.HTTPException as exc:
                details.append(f"Error al crear el canal #{item.get('name')}: {exc}")

        for item in data.get("voiceChannels") or []:
            try:
                common = {"category": categories.get(item.get("parentName") or ""), "reason": "Backup restore",
                          "overwrites": _restore_overwrites(guild, roles, item.get("permissionOverwrites"))}
                if item.get("type") == discord.ChannelType.stage_voice.value:
                    await guild.create_stage_channel(item["name"], **common)
                else:
                    await guild.create_voice_channel(item["name"], bitrate=min(int(item.get("bitrate") or 64000),
                                                                               int(guild.bitrate_limit)),
                                                     user_limit=int(item.get("userLimit") or 0), **common)
                details.append(f"Canal de voz creado: {item['name']}")
            except discord.HTTPException as exc:
                details.append(f"Error al crear el canal de voz {item.get('name')}: {exc}")
        return True, details
    except Exception as exc:
        log.exception("Error restoring backup")
        return False, [*details, f"Error fatal: {exc}"]


class Backups(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot

    respaldo = app_commands.Group(name="respaldo", description="Gestion de respaldos del servidor", guild_only=True,
                                  default_permissions=discord.Permissions(administrator=True),
                                  extras={"module": "backup", "cooldown": 10, "permissions": ["administrator"]})

    async def _find(self, guild_id: int, prefix: str) -> Backup | None:
        async with self.bot.db.session() as session:
            return (await session.execute(select(Backup).where(
                Backup.guild_id == str(guild_id), Backup.id.startswith(prefix)).limit(1))).scalar_one_or_none()

    @respaldo.command(name="crear", description="Crear un respaldo de este servidor")
    @app_commands.describe(nombre="Nombre del respaldo")
    async def create(self, interaction: discord.Interaction, nombre: str) -> None:
        guild = interaction.guild
        assert guild is not None
        await interaction.response.defer(ephemeral=True)
        data = create_backup_data(guild)
        backup = Backup(guild_id=str(guild.id), creator_id=str(interaction.user.id), name=nombre, data=data,
                        size=len(json.dumps(data).encode()))
        async with self.bot.db.session() as session:
            session.add(backup)
        embed = discord.Embed(color=module_color("backup"), title="Respaldo Creado", timestamp=discord.utils.utcnow())
        for name, value in (("Nombre", nombre), ("ID", f"`{backup.id}`"), ("Tamano", f"{backup.size / 1024:.1f} KB"),
                            ("Roles", str(len(data["roles"]))),
                            ("Channels", str(len(data["textChannels"]) + len(data["voiceChannels"]))),
                            ("Categorias", str(len(data["categories"])))):
            embed.add_field(name=name, value=value, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @respaldo.command(name="lista", description="Listar todos los respaldos de este servidor")
    async def list_(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.session() as session:
            rows = (await session.execute(select(Backup.id, Backup.name, Backup.size, Backup.created_at).where(
                Backup.guild_id == str(interaction.guild_id)).order_by(Backup.created_at.desc()).limit(20))).all()
        if not rows:
            await interaction.response.send_message("No se encontraron respaldos para este servidor.", ephemeral=True)
            return
        lines = [f"**{i}.** `{bid[:8]}` — **{name}** ({size / 1024:.1f} KB) — {discord_ts(created)}"
                 for i, (bid, name, size, created) in enumerate(rows, 1)]
        embed = discord.Embed(color=module_color("backup"), title="Respaldos del Servidor", description="\n".join(lines))
        embed.set_footer(text=f"{len(rows)} respaldo(s) | Usa /respaldo info <id> para detalles")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @respaldo.command(name="restaurar", description="Restaurar un respaldo (ADVERTENCIA: destructivo)")
    @app_commands.describe(id="ID del respaldo", limpiar="Limpiar canales/roles existentes antes de restaurar")
    async def restore(self, interaction: discord.Interaction, id: str, limpiar: bool = False) -> None:
        guild = interaction.guild
        assert guild is not None
        backup = await self._find(guild.id, id)
        if backup is None:
            await interaction.response.send_message("Respaldo no encontrado.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ok, details = await restore_backup_data(guild, backup.data, limpiar)
        listed = "\n".join(details[:20]) or "Sin detalles"
        more = f"\n... y {len(details) - 20} mas" if len(details) > 20 else ""
        embed = discord.Embed(color=module_color("backup") if ok else ERROR,
                              title="Respaldo Restaurado" if ok else "Error al Restaurar",
                              description=f"**Respaldo:** {backup.name}\n\n{listed}{more}"[:4096],
                              timestamp=discord.utils.utcnow())
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.HTTPException:
            log.info("Backup %s restored in %s (original channel no longer exists)", backup.id, guild.id)

    @respaldo.command(name="eliminar", description="Eliminar un respaldo")
    @app_commands.describe(id="ID del respaldo")
    async def delete_(self, interaction: discord.Interaction, id: str) -> None:
        backup = await self._find(interaction.guild_id or 0, id)
        if backup is None:
            await interaction.response.send_message("Respaldo no encontrado.", ephemeral=True)
            return
        async with self.bot.db.session() as session:
            await session.execute(delete(Backup).where(Backup.id == backup.id))
        await interaction.response.send_message(f"Respaldo **{backup.name}** eliminado.", ephemeral=True)

    @respaldo.command(name="info", description="Ver detalles de un respaldo")
    @app_commands.describe(id="ID del respaldo")
    async def info(self, interaction: discord.Interaction, id: str) -> None:
        backup = await self._find(interaction.guild_id or 0, id)
        if backup is None:
            await interaction.response.send_message("Respaldo no encontrado.", ephemeral=True)
            return
        data = backup.data or {}
        embed = discord.Embed(color=module_color("backup"), title=f"Respaldo: {backup.name}", timestamp=discord.utils.utcnow())
        for name, value in (("ID", f"`{backup.id}`"), ("Creado por", f"<@{backup.creator_id}>"),
                            ("Creado", discord_ts(backup.created_at, "F")), ("Tamano", f"{backup.size / 1024:.1f} KB"),
                            ("Nombre del servidor", data.get("name") or "N/A"), ("Roles", str(len(data.get("roles") or []))),
                            ("Categorias", str(len(data.get("categories") or []))),
                            ("Canales de texto", str(len(data.get("textChannels") or []))),
                            ("Canales de voz", str(len(data.get("voiceChannels") or [])))):
            embed.add_field(name=name, value=value, inline=True)
        embed.set_footer(text="Usa /respaldo restaurar <id> para restaurar este respaldo")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Backups(bot))
