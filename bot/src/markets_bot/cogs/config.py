"""``/configuracion`` (modules, channels, automod) and ``/crear-texto`` (custom text commands)."""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.dialects.postgresql import insert

from markets_bot.bot import MarketsBot
from markets_bot.core import command_sync
from markets_bot.core.guild_config import MODULE_TOGGLES
from markets_bot.core.utils import module_color
from markets_bot.db.models import CustomTextCommand

CUSTOM_NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

# Modules shown in /configuracion modulo (same labels as v1, plus v2 modules).
MODULE_CHOICES = [
    app_commands.Choice(name=label, value=value)
    for label, value in (
        ("Invites", "invites"), ("Moderation", "moderation"), ("AutoMod", "automod"), ("Tickets", "tickets"),
        ("Automation", "automation"), ("Welcome", "welcome"), ("Farewell", "farewell"),
        ("Reputation", "reputation"), ("Giveaway", "giveaway"), ("Suggestions", "suggestions"),
        ("Starboard", "starboard"), ("Logging", "logging"), ("AFK", "afk"), ("Sticky", "sticky"),
        ("Rifas", "rifa"), ("Backups", "backup"), ("Niveles", "leveling"), ("Economía", "economy"),
        ("Diversión / roleplay", "fun"), ("Verificación", "verification"), ("Voz temporal", "tempvoice"),
    )
]
STATUS_ORDER = [c.value for c in MODULE_CHOICES]


def normalize_custom_name(raw: str) -> str:
    return raw.strip().removeprefix("/").lower()


class Config(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot

    configuracion = app_commands.Group(
        name="configuracion", description="Comandos de configuracion del bot", guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
        extras={"module": "config", "cooldown": 3, "permissions": ["manage_guild"]},
    )
    modulo = app_commands.Group(name="modulo", description="Activar o desactivar modulos", parent=configuracion)
    establecer = app_commands.Group(name="establecer", description="Establecer valores de configuracion",
                                    parent=configuracion)
    automod = app_commands.Group(name="automod", description="Configuracion de AutoMod", parent=configuracion)

    async def _set(self, interaction: discord.Interaction, message: str, **values: object) -> None:
        assert interaction.guild_id is not None
        await self.bot.configs.update(interaction.guild_id, **values)
        await interaction.response.send_message(message, ephemeral=True)

    # ── Modules ──────────────────────────────────────────────────────────

    @modulo.command(name="activar", description="Activar un modulo")
    @app_commands.describe(name="Modulo a activar")
    @app_commands.choices(name=MODULE_CHOICES)
    async def module_enable(self, interaction: discord.Interaction, name: app_commands.Choice[str]) -> None:
        await self._set(interaction, f"✅ El módulo **{name.value}** ha sido **activado**.",
                        **{MODULE_TOGGLES[name.value]: True})
        if name.value == "invites":  # invite commands are only deployed while the module is on
            await command_sync.sync_guild(self.bot, interaction.guild_id or 0)

    @modulo.command(name="desactivar", description="Desactivar un modulo")
    @app_commands.describe(name="Modulo a desactivar")
    @app_commands.choices(name=MODULE_CHOICES)
    async def module_disable(self, interaction: discord.Interaction, name: app_commands.Choice[str]) -> None:
        await self._set(interaction, f"❌ El módulo **{name.value}** ha sido **desactivado**.",
                        **{MODULE_TOGGLES[name.value]: False})
        if name.value == "invites":
            await command_sync.sync_guild(self.bot, interaction.guild_id or 0)

    @modulo.command(name="estado", description="Ver que modulos estan activados/desactivados")
    async def module_status(self, interaction: discord.Interaction) -> None:
        config = await self.bot.configs.get(interaction.guild_id or 0)
        lines = [
            f"{'✅' if getattr(config, MODULE_TOGGLES[m]) else '❌'} **{m.capitalize()}**" for m in STATUS_ORDER
        ]
        embed = discord.Embed(color=module_color("config"), title="Estado de Módulos", description="\n".join(lines),
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text="Usa /configuracion modulo activar/desactivar <name> para cambiarlo")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Channels / roles ─────────────────────────────────────────────────

    @establecer.command(name="bienvenida", description="Configurar mensajes de bienvenida")
    @app_commands.describe(canal="Canal de bienvenida",
                           mensaje="Mensaje de bienvenida (usa {user}, {server}, {inviter}, {memberCount})",
                           imagen="Activar tarjeta de bienvenida con imagen")
    async def set_welcome(self, interaction: discord.Interaction, canal: discord.TextChannel,
                          mensaje: str | None = None, imagen: bool | None = None) -> None:
        values: dict[str, object] = {"welcome_channel_id": str(canal.id)}
        if mensaje:
            values["welcome_message"] = mensaje
        if imagen is not None:
            values["welcome_image_enabled"] = imagen
        extra = (" Mensaje actualizado." if mensaje else "") + (
            f" Imagen de bienvenida {'activada' if imagen else 'desactivada'}." if imagen is not None else ""
        )
        await self._set(interaction, f"Canal de bienvenida establecido en {canal.mention}.{extra}", **values)

    @establecer.command(name="despedida", description="Configurar mensajes de despedida")
    @app_commands.describe(canal="Canal de despedida", mensaje="Mensaje de despedida (usa {user}, {server}, {memberCount})")
    async def set_farewell(self, interaction: discord.Interaction, canal: discord.TextChannel,
                           mensaje: str | None = None) -> None:
        values: dict[str, object] = {"farewell_channel_id": str(canal.id)}
        if mensaje:
            values["farewell_message"] = mensaje
        await self._set(interaction, f"Canal de despedida establecido en {canal.mention}."
                        + (" Mensaje actualizado." if mensaje else ""), **values)

    @establecer.command(name="modlog", description="Establecer el canal de logs de moderacion")
    @app_commands.describe(canal="Canal de logs de moderacion")
    async def set_modlog(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        await self._set(interaction, f"Canal de logs de moderacion establecido en {canal.mention}.",
                        mod_log_channel_id=str(canal.id))

    @establecer.command(name="messagelog", description="Establecer el canal de logs de edicion/eliminacion")
    @app_commands.describe(canal="Canal de logs de mensajes")
    async def set_messagelog(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        await self._set(interaction, f"Canal de logs de mensajes establecido en {canal.mention}.",
                        message_log_channel_id=str(canal.id))

    @establecer.command(name="joinleavelog", description="Establecer el canal de logs de entradas/salidas")
    @app_commands.describe(canal="Canal de logs de entradas/salidas")
    async def set_joinleave(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        await self._set(interaction, f"Canal de logs de entradas/salidas establecido en {canal.mention}.",
                        join_leave_log_channel_id=str(canal.id))

    @establecer.command(name="joinrole", description="Agregar o quitar un autorol al entrar")
    @app_commands.describe(rol="Rol para autoasignar al entrar", quitar="Quitar este rol de los roles de entrada")
    async def set_joinrole(self, interaction: discord.Interaction, rol: discord.Role, quitar: bool = False) -> None:
        config = await self.bot.configs.get(interaction.guild_id or 0)
        roles = [r for r in (config.join_role_ids or []) if r != str(rol.id)]
        if not quitar:
            roles.append(str(rol.id))
        message = (f"Se quitó **{rol.name}** de los roles de entrada." if quitar
                   else f"Se agregó **{rol.name}** como rol de entrada.")
        await self._set(interaction, message, join_role_ids=roles)

    @establecer.command(name="muterole", description="Establecer el rol de silencio")
    @app_commands.describe(rol="Rol de silencio")
    async def set_muterole(self, interaction: discord.Interaction, rol: discord.Role) -> None:
        await self._set(interaction, f"Rol de silencio establecido en **{rol.name}**.", mute_role_id=str(rol.id))

    @establecer.command(name="starboard", description="Configurar ajustes de starboard")
    @app_commands.describe(canal="Canal de starboard", umbral="Estrellas necesarias (por defecto: 3)",
                           emoji="Emoji de estrella (por defecto: estrella)")
    async def set_starboard(self, interaction: discord.Interaction, canal: discord.TextChannel,
                            umbral: app_commands.Range[int, 1, 25] | None = None, emoji: str | None = None) -> None:
        values: dict[str, object] = {"starboard_channel_id": str(canal.id)}
        if umbral is not None:
            values["starboard_threshold"] = umbral
        if emoji:
            values["starboard_emoji"] = emoji
        message = (f"Canal de starboard establecido en {canal.mention}."
                   + (f" Umbral: {umbral} estrellas." if umbral else "") + (f" Emoji: {emoji}" if emoji else ""))
        await self._set(interaction, message, **values)

    @establecer.command(name="suggestions", description="Configurar canal de sugerencias")
    @app_commands.describe(canal="Canal de sugerencias")
    async def set_suggestions(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        await self._set(interaction, f"Canal de sugerencias establecido en {canal.mention}.",
                        suggestions_channel_id=str(canal.id))

    @establecer.command(name="reputation", description="Configurar ajustes de reputación")
    @app_commands.describe(canal="Restringir /rep a este canal (opcional)")
    async def set_reputation(self, interaction: discord.Interaction, canal: discord.TextChannel | None = None) -> None:
        if canal is None:
            await interaction.response.send_message("No se proporcionaron ajustes.", ephemeral=True)
            return
        await self._set(interaction, f"Canal de reputación establecido en {canal.mention}.", rep_channel_id=str(canal.id))

    @establecer.command(name="auditlog", description="Establecer el canal de logs de auditoría (cambios de roles/canales)")
    @app_commands.describe(canal="Canal de logs de auditoría")
    async def set_auditlog(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        await self._set(interaction, f"Canal de logs de auditoría establecido en {canal.mention}.",
                        audit_log_channel_id=str(canal.id))

    @establecer.command(name="voicelog", description="Establecer el canal de logs de actividad de voz")
    @app_commands.describe(canal="Canal de logs de voz")
    async def set_voicelog(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        await self._set(interaction, f"Canal de logs de voz establecido en {canal.mention}.",
                        voice_log_channel_id=str(canal.id))

    @establecer.command(name="tickets", description="Configurar ajustes globales de tickets")
    @app_commands.describe(log="Canal de log de tickets", transcripcion="Canal de transcripciones",
                           categoria="Categoría por defecto para tickets", staff="Rol de staff global para tickets",
                           confirmacion_cierre="Pedir confirmación antes de cerrar",
                           dm_transcripcion="Enviar transcripción por DM al cerrar")
    async def set_tickets(
        self, interaction: discord.Interaction, log: discord.TextChannel | None = None,
        transcripcion: discord.TextChannel | None = None, categoria: discord.CategoryChannel | None = None,
        staff: discord.Role | None = None, confirmacion_cierre: bool | None = None, dm_transcripcion: bool | None = None,
    ) -> None:
        values: dict[str, object] = {}
        parts: list[str] = []
        if log:
            values["ticket_log_channel_id"] = str(log.id)
            parts.append(f"Log de tickets: {log.mention}")
        if transcripcion:
            values["ticket_transcript_channel_id"] = str(transcripcion.id)
            parts.append(f"Transcripciones: {transcripcion.mention}")
        if categoria:
            values["ticket_category_id"] = str(categoria.id)
            parts.append(f"Categoría: {categoria.mention}")
        if staff:
            config = await self.bot.configs.get(interaction.guild_id or 0)
            staff_roles = list(config.ticket_staff_role_ids or [])
            if str(staff.id) not in staff_roles:
                staff_roles.append(str(staff.id))
            values["ticket_staff_role_ids"] = staff_roles
            parts.append(f"Staff agregado: {staff.name}")
        if confirmacion_cierre is not None:
            values["ticket_close_confirmation"] = confirmacion_cierre
            parts.append(f"Confirmación de cierre: {'activada' if confirmacion_cierre else 'desactivada'}")
        if dm_transcripcion is not None:
            values["ticket_dm_transcript"] = dm_transcripcion
            parts.append(f"DM de transcripción: {'activado' if dm_transcripcion else 'desactivado'}")
        if not values:
            await interaction.response.send_message("No se proporcionaron ajustes.", ephemeral=True)
            return
        await self._set(interaction, "\n".join(parts), **values)

    # ── AutoMod ──────────────────────────────────────────────────────────

    @automod.command(name="antispam", description="Configurar anti-spam")
    @app_commands.describe(activado="Activar/desactivar", umbral="Mensajes antes de activar (por defecto 5)",
                           intervalo="Ventana de tiempo en segundos (por defecto 5)")
    async def am_antispam(self, interaction: discord.Interaction, activado: bool,
                          umbral: app_commands.Range[int, 2, 20] | None = None,
                          intervalo: app_commands.Range[int, 1, 30] | None = None) -> None:
        values: dict[str, object] = {"anti_spam_enabled": activado}
        if umbral is not None:
            values["anti_spam_threshold"] = umbral
        if intervalo is not None:
            values["anti_spam_interval"] = intervalo
        message = (f"Anti-spam {'activado' if activado else 'desactivado'}."
                   + (f" Umbral: {umbral} mensajes." if umbral else "") + (f" Intervalo: {intervalo}s." if intervalo else ""))
        await self._set(interaction, message, **values)

    @automod.command(name="anticaps", description="Configurar anti-mayusculas")
    @app_commands.describe(activado="Activar/desactivar",
                           umbral="Umbral de mayusculas en porcentaje (por defecto 70)")
    async def am_anticaps(self, interaction: discord.Interaction, activado: bool,
                          umbral: app_commands.Range[int, 30, 100] | None = None) -> None:
        values: dict[str, object] = {"anti_caps_enabled": activado}
        if umbral is not None:
            values["anti_caps_threshold"] = umbral
        await self._set(interaction, f"Anti-mayusculas {'activado' if activado else 'desactivado'}."
                        + (f" Umbral: {umbral}%." if umbral else ""), **values)

    @automod.command(name="antilinks", description="Configurar anti-enlaces")
    @app_commands.describe(activado="Activar/desactivar")
    async def am_antilinks(self, interaction: discord.Interaction, activado: bool) -> None:
        await self._set(interaction, f"Anti-enlaces {'activado' if activado else 'desactivado'}.",
                        anti_links_enabled=activado)

    @automod.command(name="blacklist", description="Agregar o quitar una palabra bloqueada")
    @app_commands.describe(palabra="Palabra a agregar/quitar", quitar="Quitar en lugar de agregar")
    async def am_blacklist(self, interaction: discord.Interaction, palabra: str, quitar: bool = False) -> None:
        word = palabra.lower()
        config = await self.bot.configs.get(interaction.guild_id or 0)
        words = [w for w in (config.blacklisted_words or []) if w != word]
        if not quitar:
            words.append(word)
        message = f"Se quitó `{word}` de la lista negra." if quitar else f"Se agregó `{word}` a la lista negra."
        await self._set(interaction, message, blacklisted_words=words)

    @automod.command(name="exempt", description="Excluir un rol o canal de automod")
    @app_commands.describe(rol="Rol a excluir", canal="Canal a excluir", quitar="Quitar exclusion")
    async def am_exempt(self, interaction: discord.Interaction, rol: discord.Role | None = None,
                        canal: discord.TextChannel | None = None, quitar: bool = False) -> None:
        if rol is None and canal is None:
            await interaction.response.send_message("Proporciona un rol o canal para excluir.", ephemeral=True)
            return
        config = await self.bot.configs.get(interaction.guild_id or 0)
        values: dict[str, object] = {}
        if rol:
            roles = [r for r in (config.automod_exempt_role_ids or []) if r != str(rol.id)]
            values["automod_exempt_role_ids"] = roles if quitar else [*roles, str(rol.id)]
        if canal:
            channels = [c for c in (config.automod_exempt_channel_ids or []) if c != str(canal.id)]
            values["automod_exempt_channel_ids"] = channels if quitar else [*channels, str(canal.id)]
        state = "quitado" if quitar else "agregado"
        message = ("Exclusión de AutoMod actualizada."
                   + (f" Rol: {rol.name} ({state})" if rol else "") + (f" Canal: {canal.mention} ({state})" if canal else ""))
        await self._set(interaction, message, **values)

    # ── /crear-texto ─────────────────────────────────────────────────────

    @app_commands.command(name="crear-texto", description="Crear o actualizar un comando personalizado que responde con texto",
                          extras={"module": "config", "cooldown": 10, "permissions": ["manage_guild"]})
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(comando="Nombre del comando, por ejemplo /tarifa", texto="Texto que respondera el comando")
    async def crear_texto(self, interaction: discord.Interaction, comando: str, texto: str) -> None:
        assert interaction.guild_id is not None
        name = normalize_custom_name(comando)
        text = texto.strip()
        if not CUSTOM_NAME_RE.match(name):
            await interaction.response.send_message(
                "El nombre debe tener 1-32 caracteres: letras minusculas, numeros, guion o guion bajo. "
                "Ejemplo: `/tarifa`.", ephemeral=True)
            return
        if not 1 <= len(text) <= 2000:
            await interaction.response.send_message("El texto debe tener entre 1 y 2000 caracteres.", ephemeral=True)
            return
        if any(c.name == name for c in self.bot.tree.get_commands()):
            await interaction.response.send_message(
                f"No puedo crear `/{name}` porque ya existe como comando del bot.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db.session() as session:
            stmt = insert(CustomTextCommand).values(
                guild_id=str(interaction.guild_id), name=name, text=text, enabled=True,
                created_by_id=str(interaction.user.id),
            )
            await session.execute(stmt.on_conflict_do_update(
                index_elements=["guildId", "name"],
                set_={"text": text, "enabled": True, "updatedAt": discord.utils.utcnow().replace(tzinfo=None)},
            ))
        await command_sync.sync_guild(self.bot, interaction.guild_id)
        await interaction.followup.send(
            f"Listo: `/{name}` respondera con el texto guardado. Tambien puedes editarlo desde el dashboard.",
            ephemeral=True)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Config(bot))
