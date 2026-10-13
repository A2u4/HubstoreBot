"""Market security: ``/seguridad-market``, ``/verificar`` and the external registration flow."""

from __future__ import annotations

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from markets_bot.bot import MarketsBot
from markets_bot.core.utils import INFO, discord_ts
from markets_bot.db.models import MarketNetworkSignal, MarketRegistration
from markets_bot.services.market_security import MarketSecurity
from markets_bot.web.internal_server import json_response, read_json

VERIFY_BUTTON_ID = "market_verify_start"


def verification_panel(guild: discord.Guild, url: str | None = None) -> tuple[discord.Embed, discord.ui.View]:
    """Same panel for the public message and the ephemeral /verificar answer."""
    icon = guild.icon.replace(format="png", size=256).url if guild.icon else None
    embed = discord.Embed(
        color=INFO, title="🛡️ Verifica tu cuenta para acceder",
        description="Este servidor utiliza un sistema externo de verificación para reducir cuentas alternas, "
                    "evasiones de sanciones y accesos desde redes restringidas.",
    )
    embed.add_field(name="Servidor", value=f"**{guild.name}**", inline=False)
    embed.set_footer(text="Al continuar podrás revisar y aceptar el aviso de privacidad. La IP original no se almacena.",
                     icon_url=icon)
    if icon:
        embed.set_thumbnail(url=icon)
    view = discord.ui.View(timeout=None)
    if url:
        view.add_item(discord.ui.Button(label="Verificar ahora", url=url))
    else:
        view.add_item(discord.ui.Button(label="Verificar ahora", style=discord.ButtonStyle.primary,
                                        custom_id=VERIFY_BUTTON_ID))
    return embed, view


class MarketSecurityCog(commands.Cog, name="MarketSecurity"):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self.market = MarketSecurity(bot)
        bot.router.exact("button", VERIFY_BUTTON_ID, self.on_verify_button)
        bot.internal.route("POST", "/internal/market/register")(self._register_route)
        bot.internal.route("POST", "/internal/market/session")(self._session_route)

    # ── Verification entry points ────────────────────────────────────────

    async def respond_with_link(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Usa este comando dentro del servidor.", ephemeral=True)
            return
        config = await self.bot.configs.get(guild.id)
        if not config.market_verification_enabled:
            await interaction.followup.send(
                "Este servidor ya no requiere verificación. Puedes acceder directamente a los canales de la comunidad.",
                ephemeral=True)
            return
        if not self.market.secure:
            await interaction.followup.send(
                "El registro está temporalmente deshabilitado hasta que el dashboard tenga una conexión HTTPS segura.",
                ephemeral=True)
            return
        url = await self.market.create_session(guild.id, interaction.user.id, interaction.user.name)
        embed, view = verification_panel(guild, url)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def on_verify_button(self, interaction: discord.Interaction) -> None:
        config = await self.bot.configs.get(interaction.guild_id or 0)
        if not config.market_verification_enabled:
            await interaction.response.send_message("La verificación externa ya no está disponible.", ephemeral=True)
            return
        await self.respond_with_link(interaction)

    @app_commands.command(name="verificar", description="Registrar tu cuenta para acceder de forma segura al Market",
                          extras={"module": "utility", "cooldown": 10, "public": True})
    @app_commands.guild_only()
    async def verificar(self, interaction: discord.Interaction) -> None:
        await self.respond_with_link(interaction)

    # ── Internal API (dashboard registration page) ───────────────────────

    async def _register_route(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        status = await self.market.complete(body.get("token"), body.get("ip"))
        return json_response({"status": status})

    async def _session_route(self, request: web.Request) -> web.Response:
        """Page metadata: brand name and whether HTTPS is configured."""
        return json_response({"secure": self.market.secure, "brand": self.bot.settings.display_name,
                              "url": self.market.url})

    # ── /seguridad-market ────────────────────────────────────────────────

    group = app_commands.Group(
        name="seguridad-market", description="Configurar y revisar la verificación segura del Market",
        guild_only=True, default_permissions=discord.Permissions(administrator=True),
        extras={"module": "moderation", "cooldown": 5, "permissions": ["administrator"]},
    )

    @group.command(name="configurar", description="Activar el registro y elegir el rol verificado")
    @app_commands.rename(canal_log="canal-log", retencion_dias="retencion-dias", detectar_vpn="detectar-vpn",
                         politica_vpn="politica-vpn", red_bloqueada="red-bloqueada")
    @app_commands.describe(rol="Rol que recibirá el usuario después de verificarse",
                           canal_log="Canal privado para registros y alertas",
                           retencion_dias="Días sin actividad antes de borrar coincidencias no sancionadas",
                           detectar_vpn="Revisar VPN, proxy, Tor, relay y hosting con IPinfo",
                           politica_vpn="Qué hacer cuando se detecta una red anónima",
                           red_bloqueada="Acción al coincidir exactamente con una red sancionada")
    @app_commands.choices(
        politica_vpn=[app_commands.Choice(name="Enviar a revisión del staff", value="review"),
                      app_commands.Choice(name="Rechazar la verificación", value="block")],
        red_bloqueada=[app_commands.Choice(name="Bloquear verificación y avisar", value="deny"),
                       app_commands.Choice(name="Ban automático (excepto staff y redes dudosas)", value="ban")],
    )
    async def configure(self, interaction: discord.Interaction, rol: discord.Role,
                        canal_log: discord.TextChannel | None = None,
                        retencion_dias: app_commands.Range[int, 7, 365] = 90, detectar_vpn: bool = False,
                        politica_vpn: str = "review", red_bloqueada: str = "deny") -> None:
        guild = interaction.guild
        assert guild is not None
        await interaction.response.defer(ephemeral=True)
        if detectar_vpn and self.bot.settings.ipinfo_token is None:
            await interaction.followup.send("No puedo activar la detección de VPN hasta configurar la clave privada de "
                                            "IPinfo en el host.", ephemeral=True)
            return
        if rol.is_default() or rol.managed or rol >= guild.me.top_role:
            await interaction.followup.send("No puedo asignar ese rol. Elige un rol normal que esté por debajo del rol "
                                            "del bot.", ephemeral=True)
            return
        await self.bot.configs.update(
            guild.id, market_verification_enabled=True, market_verification_role_id=str(rol.id),
            market_verification_log_channel_id=str(canal_log.id) if canal_log else None,
            market_verification_retention_days=retencion_dias, market_vpn_check_enabled=detectar_vpn,
            market_vpn_policy=politica_vpn, market_blocked_network_action=red_bloqueada,
        )
        notice = (f"Registro listo: {self.market.url}" if self.market.secure
                  else "La configuración quedó guardada, pero /verificar seguirá bloqueado hasta instalar HTTPS.")
        vpn = ("rechazar" if politica_vpn == "block" else "revisión") if detectar_vpn else "desactivado"
        network = "ban automático protegido" if red_bloqueada == "ban" else "bloquear y avisar"
        await interaction.followup.send(
            f"Configuración guardada. Rol: {rol.mention}. Retención: {retencion_dias} días. VPN: {vpn}. "
            f"Red sancionada: {network}.\n{notice}", ephemeral=True)

    @group.command(name="estado", description="Ver la configuración y estadísticas del registro")
    async def status(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        config = await self.bot.configs.get(guild_id)
        registrations, blocks = await self.market.stats(guild_id)
        embed = discord.Embed(color=0x8B949E, title="Seguridad del Market")
        vpn = ("Rechazar" if config.market_vpn_policy == "block" else "Revisión") if config.market_vpn_check_enabled \
            else "Desactivado"
        for name, value in (
            ("Registro", "Activado" if config.market_verification_enabled else "Desactivado"),
            ("HTTPS", "Seguro" if self.market.secure else "Pendiente"),
            ("Usuarios registrados", str(registrations)), ("Bloqueos activos", str(blocks)),
            ("Rol verificado", f"<@&{config.market_verification_role_id}>" if config.market_verification_role_id
             else "Sin configurar"),
            ("Retención", f"{config.market_verification_retention_days} días"), ("Detector VPN", vpn),
            ("Red sancionada", "Ban automático protegido" if config.market_blocked_network_action == "ban"
             else "Bloquear y avisar"),
        ):
            embed.add_field(name=name, value=value, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="publicar", description="Publicar el panel externo de verificación")
    @app_commands.describe(canal="Canal donde se publicará el botón")
    async def publish(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        guild = interaction.guild
        assert guild is not None
        config = await self.bot.configs.get(guild.id)
        if not config.market_verification_enabled:
            await interaction.response.send_message("Primero usa `/seguridad-market configurar`.", ephemeral=True)
            return
        if not self.market.secure:
            await interaction.response.send_message(
                "No publicaré un panel inseguro. Primero hay que terminar la URL HTTPS externa.", ephemeral=True)
            return
        embed, view = verification_panel(guild)
        await canal.send(embed=embed, view=view)
        await interaction.response.send_message(f"Panel publicado en {canal.mention}.", ephemeral=True)

    @group.command(name="informacion", description="Consultar el estado de registro y las señales de una cuenta")
    @app_commands.describe(usuario="Cuenta que deseas consultar")
    async def info(self, interaction: discord.Interaction, usuario: discord.User) -> None:
        guild_id = str(interaction.guild_id)
        async with self.bot.db.session() as session:
            registration = (await session.execute(select(MarketRegistration).where(
                MarketRegistration.guild_id == guild_id, MarketRegistration.user_id == str(usuario.id)
            ))).scalar_one_or_none()
            if registration is None:
                await interaction.response.send_message(f"**{usuario.name}** no ha completado el registro.",
                                                        ephemeral=True)
                return
            latest = (await session.execute(select(MarketNetworkSignal).where(
                MarketNetworkSignal.registration_id == registration.id
            ).order_by(MarketNetworkSignal.last_seen_at.desc()).limit(1))).scalar_one_or_none()
            networks = await session.scalar(select(func.count()).select_from(MarketNetworkSignal).where(
                MarketNetworkSignal.registration_id == registration.id))
        flags = []
        if latest:
            flags = [name for name, on in (("VPN", latest.vpn_detected), ("proxy", latest.proxy_detected),
                                           ("Tor", latest.tor_detected), ("relay", latest.relay_detected),
                                           ("hosting", latest.hosting_detected)) if on]
        linked = await self.market.linked_accounts(guild_id, str(usuario.id))
        embed = discord.Embed(color=0xD98D3F if flags else 0x2F9E66, title=f"Registro de {usuario.name}")
        embed.add_field(name="Primera verificación", value=discord_ts(registration.first_seen_at, "F"), inline=True)
        embed.add_field(name="Última verificación", value=discord_ts(registration.last_seen_at), inline=True)
        embed.add_field(name="Redes registradas", value=str(networks or 0), inline=True)
        embed.add_field(name="Análisis más reciente", inline=True,
                        value=", ".join(flags) if flags else "Sin señales" if latest and latest.privacy_checked_at
                        else "No analizado")
        embed.add_field(name="Servicio detectado", value=(latest.privacy_service if latest else None) or "Ninguno",
                        inline=True)
        embed.add_field(name="Cuentas relacionadas", value=str(len(linked)), inline=True)
        embed.set_footer(text="La dirección IP original nunca se muestra ni se almacena.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="vinculados", description="Buscar cuentas con coincidencias de red para revisión manual")
    @app_commands.describe(usuario="Cuenta que deseas revisar")
    async def linked(self, interaction: discord.Interaction, usuario: discord.User) -> None:
        linked = await self.market.linked_accounts(str(interaction.guild_id), str(usuario.id))
        if not linked:
            text = f"No hay coincidencias registradas para **{usuario.name}**."
        else:
            text = (f"Coincidencias para revisión manual de **{usuario.name}**:\n"
                    + "\n".join(f"• <@{i}> (`{i}`)" for i in linked[:25])
                    + "\n\nUna coincidencia no demuestra que sea la misma persona: puede tratarse de una red "
                      "compartida o VPN.")
        await interaction.response.send_message(text, ephemeral=True)

    @group.command(name="bloquear", description="Bloquear las redes registradas por una cuenta sancionada")
    @app_commands.describe(usuario="Cuenta sancionada", razon="Motivo del bloqueo")
    async def block(self, interaction: discord.Interaction, usuario: discord.User,
                    razon: app_commands.Range[str, 1, 300] | None = None) -> None:
        count, linked = await self.market.block_networks(str(interaction.guild_id), str(usuario.id),
                                                         razon or "Bloqueo manual del staff")
        await interaction.response.send_message(
            f"Se activaron **{count}** bloqueos asociados a **{usuario.name}**. Cuentas relacionadas para revisión: "
            f"**{len(linked)}**.", ephemeral=True)

    @group.command(name="desbloquear", description="Desactivar los bloqueos creados por una cuenta")
    @app_commands.describe(usuario="Cuenta cuyo bloqueo deseas retirar")
    async def unblock(self, interaction: discord.Interaction, usuario: discord.User) -> None:
        count = await self.market.unblock_networks(str(interaction.guild_id), str(usuario.id))
        await interaction.response.send_message(f"Se desactivaron **{count}** bloqueos creados por **{usuario.name}**.",
                                                ephemeral=True)


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(MarketSecurityCog(bot))
