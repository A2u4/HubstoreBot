"""Member verification panel (Koya style): one-click button or image captcha that grants a role."""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands

from markets_bot.bot import MarketsBot
from markets_bot.core.audit import send_audit
from markets_bot.core.cache import TtlCache
from markets_bot.core.errors import UserError
from markets_bot.core.router import RoutedModal, modal_values
from markets_bot.core.utils import OK, module_color
from markets_bot.db.models import GuildConfig
from markets_bot.services.captcha import new_code, render_captcha
from markets_bot.web.internal_server import HttpError, json_response, read_json

log = logging.getLogger(__name__)

START_ID = "v2verify:start"
ANSWER_ID = "v2verify:answer"
MODAL_ID = "v2verify:modal"
MAX_ATTEMPTS = 3
COLOR = module_color("utility")


def panel_embed(config: GuildConfig, guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(color=0xFFFFFF, title=config.verification_panel_title or "Verificación",
                          description=config.verification_panel_message)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text="Captcha de imagen" if config.verification_mode == "captcha" else "Verificación con un clic")
    return embed


def panel_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Verificarme", emoji="✅", style=discord.ButtonStyle.success, custom_id=START_ID))
    return view


class Verification(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        # guild:user -> [code, attempts left]
        self._pending: TtlCache[list[object]] = TtlCache(300, 5000)
        bot.router.exact("button", START_ID, self.on_start)
        bot.router.exact("button", ANSWER_ID, self.on_answer_button)
        bot.router.exact("modal", MODAL_ID, self.on_answer_modal)
        bot.internal.route("POST", "/internal/verification/panel")(self._panel_route)

    # ── Flow ─────────────────────────────────────────────────────────────

    async def _ready(self, interaction: discord.Interaction) -> tuple[discord.Member, GuildConfig, discord.Role] | None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            return None
        config = await self.bot.configs.get(guild.id)
        role = guild.get_role(int(config.verification_role_id)) if (config.verification_role_id or "").isdigit() else None
        if not config.verification_enabled or role is None:
            await interaction.response.send_message("La verificación no está configurada en este servidor.", ephemeral=True)
            return None
        if role in interaction.user.roles:
            await interaction.response.send_message("✅ Ya estás verificado.", ephemeral=True)
            return None
        return interaction.user, config, role

    async def _grant(self, member: discord.Member, config: GuildConfig, role: discord.Role, method: str) -> bool:
        try:
            await member.add_roles(role, reason=f"Verificación ({method})")
            remove_id = config.verification_remove_role_id
            remove = member.guild.get_role(int(remove_id)) if remove_id and remove_id.isdigit() else None
            if remove and remove in member.roles:
                await member.remove_roles(remove, reason="Verificación completada")
        except discord.HTTPException as exc:
            log.error("verification: could not update roles in %s: %s", member.guild.id, exc)
            return False
        embed = discord.Embed(color=OK, title="✅ Miembro verificado", timestamp=discord.utils.utcnow(),
                              description=f"{member.mention} (`{member.id}`) se verificó por {method}.")
        embed.add_field(name="Cuenta creada", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
        await send_audit(self.bot, member.guild, embed)
        return True

    async def on_start(self, interaction: discord.Interaction) -> None:
        ready = await self._ready(interaction)
        if ready is None:
            return
        member, config, role = ready
        if config.verification_mode != "captcha":
            ok = await self._grant(member, config, role, "botón")
            await interaction.response.send_message(
                f"✅ ¡Listo! Recibiste el rol {role.mention}." if ok
                else "No pude asignarte el rol. Avisa a un administrador.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        code = new_code()
        self._pending.set(f"{member.guild.id}:{member.id}", [code, MAX_ATTEMPTS])
        png = await asyncio.to_thread(render_captcha, code)
        view = discord.ui.View(timeout=300)
        view.add_item(discord.ui.Button(label="Escribir código", emoji="⌨️", style=discord.ButtonStyle.primary,
                                        custom_id=ANSWER_ID))
        embed = discord.Embed(color=COLOR, title="🔐 Captcha",
                              description="Escribe los caracteres de la imagen (no distingue mayúsculas).\n"
                                          f"Tienes **{MAX_ATTEMPTS} intentos** y 5 minutos.")
        embed.set_image(url="attachment://captcha.png")
        await interaction.followup.send(embed=embed, file=discord.File(io.BytesIO(png), "captcha.png"), view=view,
                                        ephemeral=True)

    async def on_answer_button(self, interaction: discord.Interaction) -> None:
        if self._pending.get(f"{interaction.guild_id}:{interaction.user.id}") is None:
            await interaction.response.send_message("El captcha expiró. Pulsa **Verificarme** otra vez.", ephemeral=True)
            return
        await interaction.response.send_modal(RoutedModal(title="Verificación", custom_id=MODAL_ID, inputs=[
            discord.ui.TextInput(label="Código del captcha", custom_id="code", min_length=4, max_length=8)]))

    async def on_answer_modal(self, interaction: discord.Interaction) -> None:
        key = f"{interaction.guild_id}:{interaction.user.id}"
        pending = self._pending.get(key)
        if pending is None:
            await interaction.response.send_message("El captcha expiró. Pulsa **Verificarme** otra vez.", ephemeral=True)
            return
        answer = modal_values(interaction).get("code", "").strip().upper().replace(" ", "")
        code, attempts = str(pending[0]), int(pending[1])  # type: ignore[call-overload]
        if answer != code:
            attempts -= 1
            if attempts <= 0:
                self._pending.delete(key)
                await interaction.response.send_message("❌ Código incorrecto. Te quedaste sin intentos; pulsa "
                                                        "**Verificarme** para un captcha nuevo.", ephemeral=True)
            else:
                pending[1] = attempts
                await interaction.response.send_message(f"❌ Código incorrecto. Te quedan **{attempts}** intento(s).",
                                                        ephemeral=True)
            return
        self._pending.delete(key)
        ready = await self._ready(interaction)
        if ready is None:
            return
        member, config, role = ready
        ok = await self._grant(member, config, role, "captcha")
        await interaction.response.send_message(f"✅ ¡Verificado! Recibiste el rol {role.mention}." if ok
                                                else "No pude asignarte el rol. Avisa a un administrador.", ephemeral=True)

    # ── Admin ────────────────────────────────────────────────────────────

    admin = app_commands.Group(name="verificacion", description="Configurar el panel de verificación de miembros",
                               guild_only=True, default_permissions=discord.Permissions(manage_guild=True),
                               extras={"module": "verification", "cooldown": 3, "permissions": ["manage_guild"]})

    @admin.command(name="configurar", description="Configurar rol, modo y textos de la verificación")
    @app_commands.rename(quitar_rol="quitar-rol")
    @app_commands.describe(rol="Rol que se da al verificarse", modo="Botón simple o captcha de imagen",
                           quitar_rol="Rol que se quita al verificarse (ej. 'No verificado')",
                           titulo="Título del panel", mensaje="Texto del panel")
    @app_commands.choices(modo=[app_commands.Choice(name="Botón (un clic)", value="button"),
                                app_commands.Choice(name="Captcha de imagen", value="captcha")])
    async def configure(self, interaction: discord.Interaction, rol: discord.Role, modo: str = "button",
                        quitar_rol: discord.Role | None = None, titulo: app_commands.Range[str, 1, 256] | None = None,
                        mensaje: app_commands.Range[str, 1, 2000] | None = None) -> None:
        me = interaction.guild.me if interaction.guild else None
        if rol.managed or rol.is_default() or (me and rol >= me.top_role):
            raise UserError("No puedo asignar ese rol: está gestionado o por encima de mi rol más alto.")
        values: dict[str, object] = {"verification_enabled": True, "verification_role_id": str(rol.id),
                                     "verification_mode": modo,
                                     "verification_remove_role_id": str(quitar_rol.id) if quitar_rol else None}
        if titulo:
            values["verification_panel_title"] = titulo
        if mensaje:
            values["verification_panel_message"] = mensaje
        await self.bot.configs.update(interaction.guild_id or 0, **values)
        await interaction.response.send_message(
            f"✅ Verificación activada: {rol.mention} · modo **{'captcha' if modo == 'captcha' else 'botón'}**"
            f"{f' · quita {quitar_rol.mention}' if quitar_rol else ''}.\nPublica el panel con `/verificacion panel`.",
            ephemeral=True)

    @admin.command(name="panel", description="Publicar (o actualizar) el panel de verificación")
    @app_commands.describe(canal="Canal donde publicar el panel")
    async def panel(self, interaction: discord.Interaction, canal: discord.TextChannel | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        config = await self.bot.configs.get(guild.id)
        if not config.verification_role_id:
            raise UserError("Primero configura el rol con `/verificacion configurar`.")
        channel = canal or (guild.get_channel(int(config.verification_channel_id))
                            if (config.verification_channel_id or "").isdigit() else None) or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            raise UserError("Elige un canal de texto.")
        await interaction.response.defer(ephemeral=True)
        message = await self.publish_panel(guild, channel, config)
        await interaction.followup.send(f"✅ Panel publicado en {channel.mention} ({message.jump_url}).", ephemeral=True)

    async def publish_panel(self, guild: discord.Guild, channel: discord.TextChannel, config: GuildConfig) -> discord.Message:
        """Edit the existing panel in place when possible, otherwise post a new one."""
        if config.verification_panel_msg_id and config.verification_channel_id == str(channel.id):
            try:
                message = await channel.fetch_message(int(config.verification_panel_msg_id))
                return await message.edit(embed=panel_embed(config, guild), view=panel_view())
            except discord.HTTPException:
                pass
        message = await channel.send(embed=panel_embed(config, guild), view=panel_view())
        await self.bot.configs.update(guild.id, verification_channel_id=str(channel.id),
                                      verification_panel_msg_id=str(message.id))
        return message

    @admin.command(name="desactivar", description="Desactivar la verificación (el panel deja de dar roles)")
    async def disable(self, interaction: discord.Interaction) -> None:
        await self.bot.configs.update(interaction.guild_id or 0, verification_enabled=False)
        await interaction.response.send_message("✅ Verificación desactivada.", ephemeral=True)

    @admin.command(name="verificar-manual", description="Verificar manualmente a un miembro")
    @app_commands.describe(usuario="Miembro a verificar")
    async def manual(self, interaction: discord.Interaction, usuario: discord.Member) -> None:
        config = await self.bot.configs.get(interaction.guild_id or 0)
        role = usuario.guild.get_role(int(config.verification_role_id)) if (config.verification_role_id or "").isdigit() \
            else None
        if role is None:
            raise UserError("Primero configura el rol con `/verificacion configurar`.")
        ok = await self._grant(usuario, config, role, f"staff ({interaction.user.name})")
        await interaction.response.send_message(f"✅ {usuario.mention} verificado." if ok else "No pude asignar el rol.",
                                                ephemeral=True)

    async def _panel_route(self, request: web.Request) -> web.Response:
        """Dashboard "publish panel" button: posts/updates the panel in the configured channel."""
        body = await read_json(request)
        guild = self.bot.get_guild(int(body.get("guildId") or 0))
        if guild is None:
            raise HttpError(404, "Guild not available")
        self.bot.configs.invalidate(guild.id)
        config = await self.bot.configs.get(guild.id)
        channel_id = config.verification_channel_id or ""
        channel = guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
        if not isinstance(channel, discord.TextChannel) or not config.verification_role_id:
            raise HttpError(400, "Configura el canal y el rol de verificación primero")
        message = await self.publish_panel(guild, channel, config)
        return json_response({"ok": True, "messageId": str(message.id), "url": message.jump_url})

async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Verification(bot))
