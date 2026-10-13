"""Utility commands: /ayuda, /servidor, /usuario, /perfil, /embed, /anunciar, /dashboard, /pago-colombia."""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from markets_bot.bot import MarketsBot
from markets_bot.core.tree import command_extras
from markets_bot.core.utils import INFO, discord_ts, module_color, parse_color
from markets_bot.db.models import EconomyAccount, Invite, Marriage, MemberLevel, Reputation

MODULE_EMOJI = {"invites": "📨", "moderation": "🛡️", "automod": "🤖", "tickets": "🎫", "automation": "⚡",
                "reputation": "⭐", "giveaway": "🎉", "suggestions": "💡", "config": "⚙️", "utility": "🔧",
                "backup": "💾", "sticky": "📌", "afk": "💤", "starboard": "✨", "logging": "📝", "rifa": "🎟️",
                "shop": "🛍️", "leveling": "📈", "economy": "🪙", "fun": "🎲", "verification": "✅",
                "tempvoice": "🔊"}
MODULE_NAME = {"invites": "Invitaciones", "moderation": "Moderación", "automod": "AutoMod", "tickets": "Tickets",
               "automation": "Automatización", "reputation": "Reputación", "giveaway": "Sorteos",
               "suggestions": "Sugerencias", "config": "Configuración", "utility": "Utilidades", "backup": "Respaldos",
               "sticky": "Mensajes Fijos", "afk": "AFK", "starboard": "Starboard", "logging": "Registros",
               "rifa": "Rifas", "shop": "Tienda", "leveling": "Niveles", "economy": "Economía",
               "fun": "Diversión", "verification": "Verificación", "tempvoice": "Voz temporal"}
MODULE_ORDER = ["moderation", "utility", "fun", "economy", "leveling", "sticky", "afk", "automation", "config",
                "invites", "tickets", "shop", "reputation", "giveaway", "rifa", "suggestions", "starboard",
                "verification", "tempvoice", "backup", "logging"]
VERIFICATION = {0: "Ninguno", 1: "Bajo", 2: "Medio", 3: "Alto", 4: "Muy alto"}
CONTENT_FILTER = {0: "Desactivado", 1: "Sin rol", 2: "Todos"}
PAYMENT_IMAGE = Path(os.environ.get("PAGO_COLOMBIA_IMAGE", Path(__file__).resolve().parents[4] / "uploads" / "pago-colombia.jpg"))


def _leaf_commands(command: Any) -> list[Any]:
    if isinstance(command, app_commands.Group):
        return [leaf for child in command.commands for leaf in _leaf_commands(child)]
    return [command]


class Utility(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot

    # ── /ayuda (generated from the command tree) ─────────────────────────

    def _visible_commands(self, interaction: discord.Interaction) -> dict[str, list[Any]]:
        perms = interaction.permissions
        grouped: dict[str, list[Any]] = defaultdict(list)
        for command in self.bot.tree.get_commands(type=discord.AppCommandType.chat_input):
            required = command.default_permissions
            if required is not None and not perms.administrator and not perms >= required:
                continue  # hide commands Discord itself would not show to this member
            grouped[command_extras(command).get("module") or "utility"].append(command)
        return dict(sorted(grouped.items(), key=lambda item: MODULE_ORDER.index(item[0])
                           if item[0] in MODULE_ORDER else 999))

    def _module_embed(self, module: str, commands_: list[Any]) -> discord.Embed:
        lines = []
        for command in sorted(commands_, key=lambda c: c.name):
            lines.append(f"**/{command.name}** — {command.description}")
            if isinstance(command, app_commands.Group):
                lines.extend(f"  ╰ `/{leaf.qualified_name}` — {leaf.description}" for leaf in _leaf_commands(command))
            lines.append("")
        embed = discord.Embed(color=module_color(module), title=f"{MODULE_EMOJI.get(module, '📦')} Módulo: "
                                                                 f"{MODULE_NAME.get(module, module)}",
                              description="\n".join(lines).strip()[:4096], timestamp=discord.utils.utcnow())
        embed.set_footer(text="Usa /ayuda comando:<nombre> para más detalles")
        return embed

    @app_commands.command(name="ayuda", description="Ver los comandos disponibles del bot",
                          extras={"module": "utility", "cooldown": 5, "public": True})
    @app_commands.describe(comando="Ver detalles de un comando específico")
    async def help(self, interaction: discord.Interaction, comando: str | None = None) -> None:
        modules = self._visible_commands(interaction)
        if comando:
            name = comando.strip().removeprefix("/").split()[0].lower()
            command = self.bot.tree.get_command(name)
            if command is None:
                await interaction.response.send_message(f"No encontré el comando `/{name}`.", ephemeral=True)
                return
            extras = command_extras(command)
            module = extras.get("module") or "utility"
            embed = discord.Embed(color=module_color(module), title=f"{MODULE_EMOJI.get(module, '📦')} /{command.name}",
                                  description=command.description, timestamp=discord.utils.utcnow())
            embed.add_field(name="📁 Módulo", value=MODULE_NAME.get(module, module), inline=True)
            embed.add_field(name="⏱️ Cooldown", value=f"{extras.get('cooldown', 3)}s", inline=True)
            if isinstance(command, app_commands.Group):
                embed.add_field(name="📋 Subcomandos", inline=False, value="\n\n".join(
                    f"`/{leaf.qualified_name}`\n╰ {leaf.description}" for leaf in _leaf_commands(command))[:1024])
            if extras.get("permissions"):
                embed.add_field(name="🔒 Permisos requeridos", value="Requiere permisos de administración/moderación",
                                inline=False)
            embed.set_footer(text="Usa /ayuda para ver todos los módulos")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        name = self.bot.user.name if self.bot.user else "Bot"
        total = sum(len(c) for c in modules.values())
        main = discord.Embed(color=INFO, timestamp=discord.utils.utcnow(), description=(
            f"Bienvenido al centro de ayuda de **{name}**.\n\n📌 Selecciona un módulo en el **menú de abajo** para ver "
            "sus comandos en detalle.\n📌 Usa `/ayuda comando:<nombre>` para ver subcomandos y detalles de un comando.\n"
            "📌 Escribe `+rep @usuario` en el chat para dar reputación rápidamente."))
        main.set_author(name=f"{name} — Centro de Ayuda", icon_url=self.bot.user.display_avatar.url if self.bot.user else None)
        for module, cmds in modules.items():
            main.add_field(name=f"{MODULE_EMOJI.get(module, '📦')} {MODULE_NAME.get(module, module)} ({len(cmds)})",
                           value=" ".join(f"`/{c.name}`" for c in sorted(cmds, key=lambda c: c.name))[:1024], inline=False)
        main.set_footer(text=f"{total} comandos en {len(modules)} módulos • Selecciona un módulo ↓")

        cog = self

        class HelpView(discord.ui.View):
            def __init__(self) -> None:
                super().__init__(timeout=180)
                select = discord.ui.Select(placeholder="📂 Selecciona un módulo para ver detalles...", options=[
                    discord.SelectOption(label=MODULE_NAME.get(m, m.capitalize()), value=m,
                                         description=f"{len(c)} comando{'' if len(c) == 1 else 's'}",
                                         emoji=MODULE_EMOJI.get(m, "📦")) for m, c in list(modules.items())[:25]])
                select.callback = self.pick  # type: ignore[method-assign]
                self.select = select
                self.add_item(select)

            async def interaction_check(self, i: discord.Interaction) -> bool:
                return i.user.id == interaction.user.id

            async def pick(self, i: discord.Interaction) -> None:
                module = self.select.values[0]
                if not any(isinstance(c, discord.ui.Button) for c in self.children):
                    back = discord.ui.Button(label="← Inicio", style=discord.ButtonStyle.secondary, row=1)
                    back.callback = self.home  # type: ignore[method-assign]
                    self.add_item(back)
                await i.response.edit_message(embed=cog._module_embed(module, modules[module]), view=self)

            async def home(self, i: discord.Interaction) -> None:
                await i.response.edit_message(embed=main, view=self)

            async def on_timeout(self) -> None:
                for child in self.children:
                    child.disabled = True  # type: ignore[attr-defined]
                try:
                    await interaction.edit_original_response(view=self)
                except discord.HTTPException:
                    pass

        await interaction.response.send_message(embed=main, view=HelpView())

    # ── Server / user info ───────────────────────────────────────────────

    async def _server_info(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Este comando solo funciona en servidores.", ephemeral=True)
            return
        await interaction.response.defer()
        owner = guild.owner or (await guild.fetch_member(guild.owner_id) if guild.owner_id else None)
        try:
            bans = len([b async for b in guild.bans(limit=None)])
        except discord.HTTPException:
            bans = None
        channels = guild.channels
        count = lambda kind: sum(1 for c in channels if c.type is kind)  # noqa: E731
        humans = sum(1 for m in guild.members if not m.bot)
        bots = sum(1 for m in guild.members if m.bot)
        online = sum(1 for m in guild.members if m.status is not discord.Status.offline)
        icon = guild.icon.with_size(512).url if guild.icon else None
        embed = discord.Embed(color=module_color("utility"), title=guild.name,
                              description=guild.description or "Resumen del servidor", timestamp=discord.utils.utcnow())
        embed.set_author(name=guild.name, icon_url=icon)
        if icon:
            embed.set_thumbnail(url=icon)
        embed.add_field(name="Identidad", inline=False, value="\n".join([
            f"ID: `{guild.id}`", f"Duenio: {f'{owner.mention} (`{owner.id}`)' if owner else 'Desconocido'}",
            f"Creado: {discord_ts(guild.created_at, 'F')} ({discord_ts(guild.created_at)})"]))
        embed.add_field(name="Miembros", inline=True, value="\n".join([
            f"Total: **{guild.member_count}**", f"Humanos: **{humans or 'N/D'}**", f"Bots: **{bots or 'N/D'}**",
            f"Online cache: **{online}**"]))
        channel_lines = [f"Texto: **{count(discord.ChannelType.text)}**", f"Voz: **{count(discord.ChannelType.voice)}**",
                         f"Categorias: **{count(discord.ChannelType.category)}**"]
        for label, kind in (("Foros", discord.ChannelType.forum), ("Escenario", discord.ChannelType.stage_voice),
                            ("Anuncios", discord.ChannelType.news)):
            if count(kind):
                channel_lines.append(f"{label}: **{count(kind)}**")
        embed.add_field(name=f"Canales ({len(channels)})", value="\n".join(channel_lines), inline=True)
        embed.add_field(name="Comunidad", inline=True, value="\n".join([
            f"Roles: **{max(0, len(guild.roles) - 1)}**", f"Emojis: **{len(guild.emojis)}**",
            f"Stickers: **{len(guild.stickers)}**",
            f"Boosts: **{guild.premium_subscription_count or 0}** (nivel {guild.premium_tier})"]))
        embed.add_field(name="Seguridad", inline=False, value="\n".join([
            f"Verificacion: **{VERIFICATION.get(guild.verification_level.value, 'Desconocido')}**",
            f"Filtro contenido: **{CONTENT_FILTER.get(guild.explicit_content_filter.value, 'Desconocido')}**",
            f"Notificaciones: **{'Solo menciones' if guild.default_notifications.value == 1 else 'Todos los mensajes'}**",
            f"Baneados: **{bans if bans is not None else 'N/D'}**"]))
        embed.set_footer(text=f"Solicitado por {interaction.user.name}")
        if guild.banner:
            embed.set_image(url=guild.banner.with_size(1024).url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="servidor", description="Ver informacion sobre este servidor",
                          extras={"module": "utility", "cooldown": 10, "public": True})
    @app_commands.guild_only()
    async def servidor(self, interaction: discord.Interaction) -> None:
        await self._server_info(interaction)

    @app_commands.command(name="server", description="Show server information",
                          extras={"module": "utility", "cooldown": 10, "public": True})
    @app_commands.guild_only()
    async def server(self, interaction: discord.Interaction) -> None:
        await self._server_info(interaction)

    @app_commands.command(name="usuario", description="Ver información sobre un usuario",
                          extras={"module": "utility", "cooldown": 5})
    @app_commands.describe(usuario="Usuario a consultar (por defecto: tú mismo)")
    async def user_info(self, interaction: discord.Interaction, usuario: discord.User | None = None) -> None:
        user = usuario or interaction.user
        member = interaction.guild.get_member(user.id) if interaction.guild else None
        badges = [flag.name.replace("_", " ").title() for flag in user.public_flags.all()]
        embed = discord.Embed(color=member.color.value if member and member.color.value else module_color("utility"),
                              timestamp=discord.utils.utcnow())
        embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.with_size(512).url)
        embed.add_field(name="ID", value=str(user.id), inline=True)
        embed.add_field(name="Bot", value="Sí" if user.bot else "No", inline=True)
        embed.add_field(name="Creado", value=f"{discord_ts(user.created_at, 'F')}\n({discord_ts(user.created_at)})", inline=True)
        embed.add_field(name="Insignias", value=", ".join(badges) or "Ninguna", inline=False)
        if member is not None:
            roles = [r.mention for r in sorted(member.roles, key=lambda r: r.position, reverse=True) if not r.is_default()][:20]
            joined = member.joined_at
            embed.add_field(name="Se unió al servidor", inline=True,
                            value=f"{discord_ts(joined, 'F')}\n({discord_ts(joined)})" if joined else "Desconocido")
            embed.add_field(name="Apodo", value=member.nick or "Ninguno", inline=True)
            embed.add_field(name="Boosteando", value=discord_ts(member.premium_since) if member.premium_since
                            else "No está boosteando", inline=True)
            embed.add_field(name=f"Roles [{len(roles)}]", value=", ".join(roles) or "Ninguno", inline=False)
            if member.color.value:
                embed.add_field(name="Color de visualización", value=str(member.color), inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /perfil (reps, invites, level, economy, marriage) ────────────────

    async def _profile_embed(self, member: discord.Member) -> tuple[discord.Embed, int, int]:
        rep_cog = self.bot.get_cog("Reputation")
        gid, uid = str(member.guild.id), str(member.id)
        rep_total = await rep_cog.service.total(gid, uid) if rep_cog else 0  # type: ignore[attr-defined]
        async with self.bot.db.session() as session:
            given = await session.scalar(select(func.count()).select_from(Reputation).where(
                Reputation.guild_id == gid, Reputation.giver_id == uid)) or 0
            invites = await session.scalar(select(func.count()).select_from(Invite).where(
                Invite.guild_id == gid, Invite.inviter_id == uid, Invite.fake.is_(False), Invite.left.is_(False))) or 0
            last = (await session.execute(select(Reputation).where(Reputation.guild_id == gid, Reputation.user_id == uid)
                                          .order_by(Reputation.created_at.desc()).limit(3))).scalars().all()
            level = (await session.execute(select(MemberLevel).where(
                MemberLevel.guild_id == gid, MemberLevel.user_id == uid))).scalar_one_or_none()
            account = (await session.execute(select(EconomyAccount).where(
                EconomyAccount.guild_id == gid, EconomyAccount.user_id == uid))).scalar_one_or_none()
            marriage = (await session.execute(select(Marriage).where(
                Marriage.guild_id == gid, (Marriage.user1_id == uid) | (Marriage.user2_id == uid)))).scalar_one_or_none()
        config = await self.bot.configs.get(member.guild.id)
        top = member.top_role if not member.top_role.is_default() else None
        bar_len = 10
        filled = round(rep_total / max(rep_total, 50) * bar_len) if rep_total else 0
        embed = discord.Embed(color=top.color.value if top and top.color.value else INFO, timestamp=discord.utils.utcnow())
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.with_size(128).url)
        embed.set_thumbnail(url=member.display_avatar.with_size(256).url)
        embed.add_field(name="⭐ Reputación", inline=False,
                        value=f"**{rep_total}** recibidas  •  **{given}** dadas\n`{'█' * filled}{'░' * (bar_len - filled)}`")
        embed.add_field(name="📨 Invitaciones", value=f"**{invites}** miembros invitados", inline=True)
        embed.add_field(name="👑 Rol más alto", value=top.mention if top else "_Ninguno_", inline=True)
        if member.joined_at:
            days = (discord.utils.utcnow() - member.joined_at).days
            embed.add_field(name="📅 En el servidor", value=f"**{days}** días\n{discord_ts(member.joined_at, 'D')}", inline=True)
        embed.add_field(name="🎂 Cuenta de Discord", value=discord_ts(member.created_at, "D"), inline=True)
        if config.leveling_enabled and level is not None:
            embed.add_field(name="📈 Nivel", value=f"Nivel **{level.level}** · {level.xp:,} XP", inline=True)
        if config.economy_enabled and account is not None:
            embed.add_field(name=f"{config.currency_symbol} Economía", inline=True,
                            value=f"**{account.wallet + account.bank:,}** {config.currency_name}")
        if marriage is not None:
            partner = marriage.user2_id if marriage.user1_id == uid else marriage.user1_id
            embed.add_field(name="💍 Pareja", value=f"<@{partner}> desde {discord_ts(marriage.created_at, 'D')}", inline=True)
        preview = "\n".join(f"⭐ <@{r.giver_id}> — {f'\"{r.reason}\"' if r.reason else '_sin razón_'} • {discord_ts(r.created_at)}"
                            for r in last) or "_Aún no tiene reps recibidas_"
        embed.add_field(name="💬 Últimas reps recibidas", value=preview[:1024], inline=False)
        embed.set_footer(text=f"ID: {uid}")
        return embed, rep_total, int(given)

    async def _reps_page(self, guild_id: int, user_id: int, received: bool, page: int, name: str) -> tuple[discord.Embed, int]:
        config = await self.bot.configs.get(guild_id)
        guild_ids = [str(guild_id), *(config.rep_sync_guild_ids or [])]
        column = Reputation.user_id if received else Reputation.giver_id
        per_page = 5
        async with self.bot.db.session() as session:
            total = await session.scalar(select(func.count()).select_from(Reputation).where(
                Reputation.guild_id.in_(guild_ids), column == str(user_id))) or 0
            rows = (await session.execute(select(Reputation).where(
                Reputation.guild_id.in_(guild_ids), column == str(user_id)).order_by(Reputation.created_at.desc())
                .offset(page * per_page).limit(per_page))).scalars().all()
        pages = max(1, -(-total // per_page))
        lines = []
        for i, r in enumerate(rows):
            partner = f"<@{r.giver_id}>" if received else f"<@{r.user_id}>"
            reason = f'"{r.reason}"' if r.reason else "_sin razón_"
            lines.append(f"`{page * per_page + i + 1}.` {partner} — {reason}\n    📍 {discord_ts(r.created_at, 'd')} • "
                         f"{discord_ts(r.created_at)}")
        embed = discord.Embed(color=0xF59E0B if received else 0xEC4899,
                              title=f"⭐ Reps recibidas por {name}" if received else f"💝 Reps dadas por {name}",
                              description="\n\n".join(lines) or "_No hay registros._")
        embed.set_footer(text=f"Página {page + 1} de {pages} • {total} en total")
        return embed, pages

    @app_commands.command(name="perfil", description="Ver el perfil de un miembro del servidor",
                          extras={"module": "utility", "cooldown": 5, "public": True})
    @app_commands.guild_only()
    @app_commands.describe(usuario="Usuario a consultar (por defecto: tú mismo)")
    async def profile(self, interaction: discord.Interaction, usuario: discord.User | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        member = guild.get_member((usuario or interaction.user).id)
        if member is None:
            await interaction.response.send_message("No se encontró ese usuario en el servidor.", ephemeral=True)
            return
        await interaction.response.defer()
        embed, rep_total, rep_given = await self._profile_embed(member)
        cog = self

        class ProfileView(discord.ui.View):
            def __init__(self) -> None:
                super().__init__(timeout=120)
                self.show_profile()

            def _button(self, label: str, callback: Any, *, emoji: str | None = None, disabled: bool = False,
                        style: discord.ButtonStyle = discord.ButtonStyle.secondary) -> None:
                button = discord.ui.Button(label=label, emoji=emoji, style=style, disabled=disabled)
                button.callback = callback  # type: ignore[method-assign]
                self.add_item(button)

            def show_profile(self) -> None:
                self.clear_items()
                self._button(f"Reps recibidas ({rep_total})", lambda i: self.page(i, True, 0), emoji="⭐")
                self._button(f"Reps dadas ({rep_given})", lambda i: self.page(i, False, 0), emoji="💝")

            async def page(self, i: discord.Interaction, received: bool, number: int) -> None:
                page_embed, pages = await cog._reps_page(guild.id, member.id, received, number, member.display_name)
                self.clear_items()
                self._button("◀ Anterior", lambda x: self.page(x, received, number - 1), disabled=number == 0)
                self._button("↩ Perfil", self.back, style=discord.ButtonStyle.primary)
                self._button("Siguiente ▶", lambda x: self.page(x, received, number + 1), disabled=number >= pages - 1)
                await i.response.edit_message(embed=page_embed, view=self)

            async def back(self, i: discord.Interaction) -> None:
                fresh, _, _ = await cog._profile_embed(member)
                self.show_profile()
                await i.response.edit_message(embed=fresh, view=self)

            async def interaction_check(self, i: discord.Interaction) -> bool:
                return i.user.id == interaction.user.id

            async def on_timeout(self) -> None:
                self.show_profile()
                for child in self.children:
                    child.disabled = True  # type: ignore[attr-defined]
                try:
                    await interaction.edit_original_response(view=self)
                except discord.HTTPException:
                    pass

        await interaction.followup.send(embed=embed, view=ProfileView())

    # ── Messaging helpers ────────────────────────────────────────────────

    embed_group = app_commands.Group(name="embed", description="Crear y enviar un embed personalizado", guild_only=True,
                                     default_permissions=discord.Permissions(manage_messages=True),
                                     extras={"module": "utility", "cooldown": 5, "permissions": ["manage_messages"]})

    @embed_group.command(name="enviar", description="Enviar un embed personalizado a un canal")
    @app_commands.describe(titulo="Título del embed", descripcion="Descripción del embed", color="Color hex (ej. #5865F2)",
                           pie="Texto del pie de página", imagen="URL de imagen", miniatura="URL de miniatura",
                           canal="Canal destino (por defecto el actual)", mencionar="Mencionar antes del embed")
    @app_commands.choices(mencionar=[app_commands.Choice(name="@everyone", value="@everyone"),
                                     app_commands.Choice(name="@here", value="@here"),
                                     app_commands.Choice(name="Ninguno", value="none")])
    async def embed_send(self, interaction: discord.Interaction, titulo: str, descripcion: str, color: str | None = None,
                         pie: str | None = None, imagen: str | None = None, miniatura: str | None = None,
                         canal: discord.TextChannel | None = None, mencionar: str = "none") -> None:
        channel = canal or interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("Canal inválido.", ephemeral=True)
            return
        embed = discord.Embed(title=titulo, description=descripcion, color=parse_color(color, INFO),
                              timestamp=discord.utils.utcnow())
        if pie:
            embed.set_footer(text=pie)
        if imagen:
            embed.set_image(url=imagen)
        if miniatura:
            embed.set_thumbnail(url=miniatura)
        mention = mencionar if mencionar != "none" else None
        await channel.send(content=mention, embed=embed, allowed_mentions=discord.AllowedMentions(everyone=bool(mention)))
        await interaction.response.send_message(f"Embed enviado a <#{channel.id}>.", ephemeral=True)  # type: ignore[attr-defined]

    @embed_group.command(name="editar", description="Editar un embed existente enviado por el bot")
    @app_commands.describe(id_mensaje="ID del mensaje a editar", titulo="Nuevo título", descripcion="Nueva descripción",
                           color="Nuevo color hex", pie="Nuevo texto del pie", imagen="Nueva URL de imagen",
                           miniatura="Nueva URL de miniatura", canal="Canal que contiene el mensaje")
    async def embed_edit(self, interaction: discord.Interaction, id_mensaje: str, titulo: str | None = None,
                         descripcion: str | None = None, color: str | None = None, pie: str | None = None,
                         imagen: str | None = None, miniatura: str | None = None,
                         canal: discord.TextChannel | None = None) -> None:
        channel = canal or interaction.channel
        try:
            message = await channel.fetch_message(int(id_mensaje))  # type: ignore[union-attr]
        except (ValueError, discord.HTTPException, AttributeError):
            await interaction.response.send_message("Mensaje no encontrado.", ephemeral=True)
            return
        if message.author.id != self.bot.user.id:  # type: ignore[union-attr]
            await interaction.response.send_message("Solo puedo editar mensajes enviados por mí.", ephemeral=True)
            return
        if not message.embeds:
            await interaction.response.send_message("Ese mensaje no tiene embeds para editar.", ephemeral=True)
            return
        embed = message.embeds[0]
        if titulo:
            embed.title = titulo
        if descripcion:
            embed.description = descripcion
        if color:
            embed.color = parse_color(color, INFO)
        if pie:
            embed.set_footer(text=pie)
        if imagen:
            embed.set_image(url=imagen)
        if miniatura:
            embed.set_thumbnail(url=miniatura)
        await message.edit(embed=embed)
        await interaction.response.send_message("Embed actualizado.", ephemeral=True)

    @app_commands.command(name="anunciar", description="Enviar un anuncio formateado a un canal",
                          extras={"module": "utility", "cooldown": 10, "permissions": ["manage_messages"]})
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.describe(mensaje="Texto del anuncio (soporta markdown de Discord)",
                           canal="Canal destino (por defecto el actual)", titulo="Título del embed",
                           color="Color hex del embed (ej. #5865F2)", mencionar="Rol a mencionar con el anuncio",
                           everyone="Mencionar a @everyone", imagen="URL de imagen para adjuntar al embed",
                           publicar="Auto-publicar si se envía a un canal de anuncios")
    async def announce(self, interaction: discord.Interaction, mensaje: str, canal: discord.TextChannel | None = None,
                       titulo: str | None = None, color: str | None = None, mencionar: discord.Role | None = None,
                       everyone: bool = False, imagen: str | None = None, publicar: bool = False) -> None:
        channel = canal or interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("Canal inválido.", ephemeral=True)
            return
        embed = discord.Embed(description=mensaje, color=parse_color(color, module_color("utility")),
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"Anunciado por {interaction.user.name}")
        if titulo:
            embed.title = titulo
        if imagen:
            embed.set_image(url=imagen)
        content = " ".join(filter(None, ["@everyone" if everyone else None, mencionar.mention if mencionar else None])) or None
        sent = await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions(
            everyone=everyone, roles=[mencionar] if mencionar else False))
        is_news = isinstance(channel, discord.TextChannel) and channel.is_news()
        if publicar and is_news:
            try:
                await sent.publish()
            except discord.HTTPException:
                pass
        await interaction.response.send_message(
            f"Anuncio enviado a {channel.mention}.{' (Publicado)' if publicar and is_news else ''}", ephemeral=True)

    @app_commands.command(name="dashboard", description="Abrir el panel de administración del bot",
                          extras={"module": "utility", "cooldown": 5, "permissions": ["administrator"]})
    @app_commands.default_permissions(administrator=True)
    async def dashboard(self, interaction: discord.Interaction) -> None:
        url = f"{self.bot.settings.dashboard_url.rstrip('/')}/open/{quote(self.bot.identity)}"
        if interaction.guild_id:
            url += f"?guild={interaction.guild_id}"
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Abrir dashboard", url=url))
        await interaction.response.send_message(
            "Este enlace es solo para administradores. Al abrirlo, Discord verificará nuevamente tus permisos en el "
            "servidor.", view=view, ephemeral=True)

    @app_commands.command(name="pago-colombia", description="Enviar el método de pago de Colombia",
                          extras={"module": "utility", "cooldown": 3, "permissions": ["administrator"]})
    @app_commands.default_permissions(administrator=True)
    async def pago_colombia(self, interaction: discord.Interaction) -> None:
        if not await asyncio.to_thread(PAYMENT_IMAGE.is_file):
            await interaction.response.send_message("La imagen del método de pago de Colombia todavía no está disponible.",
                                                    ephemeral=True)
            return
        embed = discord.Embed(color=INFO, title="Método de pago · Colombia",
                              description="Escanea el código QR para realizar el pago. Después, envía el comprobante en "
                                          "tu ticket para validar la compra.")
        embed.set_image(url="attachment://pago-colombia.jpg")
        await interaction.response.send_message(embed=embed, file=discord.File(PAYMENT_IMAGE, filename="pago-colombia.jpg"),
                                                allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Utility(bot))
