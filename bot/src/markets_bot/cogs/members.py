"""Member join / leave flow: invite tracking, auto-roles, welcome & farewell, join logs."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from aiohttp import web
from discord.ext import commands

from markets_bot.bot import MarketsBot
from markets_bot.core.audit import send_audit, send_to, text_channel
from markets_bot.core.dedupe import claim_side_effect, release_side_effect
from markets_bot.core.utils import ERROR, OK, discord_ts, parse_color, render_template, truncate
from markets_bot.services.welcome_card import CardInput, card_variables, merge_layout, render_card
from markets_bot.web.internal_server import read_json

if TYPE_CHECKING:
    from markets_bot.cogs.invites import Invites
    from markets_bot.db.models import GuildConfig

log = logging.getLogger(__name__)

MAX_REMOTE_IMAGE_BYTES = 8 * 1024 * 1024


async def fetch_image(url: str) -> bytes | None:
    """Download a remote image (welcome card backgrounds) with size and type limits."""
    if not url.startswith(("https://", "http://")):
        return None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http, http.get(
            url, headers={"User-Agent": "MarketsBot/2.0 (welcome card)"}
        ) as resp:
            if resp.status != 200 or not resp.headers.get("content-type", "").startswith("image/"):
                return None
            data = await resp.content.read(MAX_REMOTE_IMAGE_BYTES + 1)
            return data if len(data) <= MAX_REMOTE_IMAGE_BYTES else None
    except (aiohttp.ClientError, TimeoutError):
        return None


async def avatar_png(user: discord.abc.User) -> bytes | None:
    for asset in (user.display_avatar.replace(format="png", size=256, static_format="png"), user.default_avatar):
        try:
            return await asset.read()
        except discord.HTTPException:
            continue
    return None


async def render_member_card(
    member: discord.Member | discord.User, guild: discord.Guild, layout: dict[str, Any] | None, inviter_name: str | None
) -> bytes:
    merged = merge_layout(layout)
    bg_url = merged["background"].get("imageUrl")
    background, avatar = await asyncio.gather(
        fetch_image(bg_url) if bg_url else asyncio.sleep(0, result=None), avatar_png(member)
    )
    variables = card_variables(
        display_name=member.display_name, username=member.name, server=guild.name,
        member_count=guild.member_count or 0, inviter=inviter_name,
    )
    return await asyncio.to_thread(render_card, CardInput(merged, variables, avatar, background))


def _template_vars(member: discord.Member, guild: discord.Guild, inviter: str, *, mention: bool) -> dict[str, str]:
    return {
        "user": member.mention if mention else member.name,
        "username": member.name,
        "tag": member.name,
        "server": guild.name,
        "memberCount": str(guild.member_count or 0),
        "inviter": inviter,
    }


class Members(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        bot.internal.route("POST", "/internal/welcome/preview")(self._preview_route)

    @property
    def invites(self) -> Invites | None:
        return self.bot.get_cog("Invites")  # type: ignore[return-value]

    async def _inviter_of(self, guild: discord.Guild, member_id: int, config: GuildConfig) -> tuple[str, str | None]:
        """(mention or 'Desconocido', username or None) of whoever invited ``member_id``."""
        if not config.invites_enabled or self.invites is None:
            return "Desconocido", None
        record = await self.invites.last_invite_for(guild.id, member_id)
        if record is None:
            return "Desconocido", None
        user = self.bot.get_user(int(record.inviter_id))
        if user is None:
            try:
                user = await self.bot.fetch_user(int(record.inviter_id))
            except discord.HTTPException:
                return f"<@{record.inviter_id}>", None
        return user.mention, user.name

    # ── Join ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        # Community servers require a verification level; mark real members as
        # verified so Discord doesn't block their messages.
        if not member.bot and not member.flags.bypasses_verification:
            try:
                await member.edit(bypass_verification=True, reason="Permitir participar manteniendo el modo Comunidad")
            except discord.HTTPException as exc:
                log.error("Could not bypass verification for %s: %s", member.id, exc)

        release_side_effect(f"leave:{guild.id}:{member.id}")
        if not claim_side_effect(f"welcome:{guild.id}:{member.id}"):
            return
        config = await self.bot.configs.get(guild.id)

        if config.invites_enabled and self.invites is not None:
            try:
                await self.invites.track_join(member)
            except Exception:
                log.exception("Invite tracking failed for %s", member.id)

        await self._assign_join_roles(member, config)
        inviter_mention, inviter_name = await self._inviter_of(guild, member.id, config)

        if config.welcome_enabled and config.welcome_channel_id:
            try:
                await self._send_welcome(member, config, inviter_mention, inviter_name)
            except discord.HTTPException as exc:
                log.error("Error sending welcome in %s: %s", guild.id, exc)

        if config.join_leave_log_channel_id:
            embed = discord.Embed(color=OK, timestamp=discord.utils.utcnow())
            embed.set_author(name="Miembro se unió", icon_url=member.display_avatar.url)
            embed.add_field(name="Usuario", value=f"{member.name} ({member.id})", inline=True)
            embed.add_field(name="Cuenta creada", value=discord_ts(member.created_at), inline=True)
            embed.add_field(name="Invitado por", value=inviter_mention, inline=True)
            embed.add_field(name="Total de miembros", value=str(guild.member_count), inline=True)
            await send_to(guild, config.join_leave_log_channel_id, embed=embed)

        audit = discord.Embed(color=OK, title="📥 Miembro se unió", timestamp=discord.utils.utcnow())
        audit.set_author(name=member.name, icon_url=member.display_avatar.url)
        audit.add_field(name="👤 Usuario", value=f"{member.mention} `{member.name}`", inline=True)
        audit.add_field(name="📅 Cuenta creada", value=discord_ts(member.created_at), inline=True)
        audit.add_field(name="📨 Invitado por", value=inviter_mention, inline=True)
        audit.add_field(name="👥 Total miembros", value=str(guild.member_count), inline=True)
        audit.set_footer(text=f"ID: {member.id}")
        await send_audit(self.bot, guild, audit, fallback_channel_id=config.join_leave_log_channel_id,
                         already_sent=[config.join_leave_log_channel_id])

    async def _assign_join_roles(self, member: discord.Member, config: GuildConfig) -> None:
        role_ids = (config.bot_join_role_ids or None) if member.bot else None
        role_ids = role_ids or config.join_role_ids or []
        me = member.guild.me
        roles = [
            role for rid in role_ids
            if rid.isdigit() and (role := member.guild.get_role(int(rid))) and role < me.top_role
        ]
        if roles:
            try:
                await member.add_roles(*roles, reason="Auto-rol al entrar")
            except discord.HTTPException as exc:
                log.error("Error assigning join roles in %s: %s", member.guild.id, exc)

    async def _send_welcome(
        self, member: discord.Member, config: GuildConfig, inviter_mention: str, inviter_name: str | None
    ) -> None:
        guild = member.guild
        channel = text_channel(guild, config.welcome_channel_id)
        if channel is None:
            return
        text = render_template(
            config.welcome_message or "Bienvenido {user} !", _template_vars(member, guild, inviter_mention, mention=True)
        )
        if config.welcome_image_enabled:
            try:
                png = await render_member_card(member, guild, config.welcome_card_layout, inviter_name)
                await channel.send(content=text, file=discord.File(io.BytesIO(png), filename="welcome.png"))
            except Exception:
                log.exception("Failed to generate welcome image")
                await channel.send(content=text)
            return

        plain_vars = _template_vars(member, guild, inviter_mention, mention=False)
        description = (
            render_template(config.welcome_embed_description, _template_vars(member, guild, inviter_mention, mention=True))
            if config.welcome_embed_description
            else text
        )
        embed = discord.Embed(
            color=parse_color(config.welcome_embed_color, OK),
            title=config.welcome_embed_title or "¡Bienvenido!",
            description=description,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=config.welcome_embed_thumbnail or member.display_avatar.with_size(256).url)
        embed.set_footer(text=render_template(config.welcome_embed_footer or "Miembro #{memberCount}", plain_vars))
        if config.welcome_embed_image:
            embed.set_image(url=config.welcome_embed_image)
        await channel.send(embed=embed)

    # ── Leave ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = member.guild
        release_side_effect(f"welcome:{guild.id}:{member.id}")
        if not claim_side_effect(f"leave:{guild.id}:{member.id}"):
            return
        config = await self.bot.configs.get(guild.id)

        if config.invites_enabled and self.invites is not None:
            try:
                await self.invites.mark_left(guild.id, member.id)
            except Exception:
                log.exception("Error marking leave for %s", member.id)

        if config.farewell_enabled and config.farewell_channel_id:
            try:
                await self._send_farewell(member, config)
            except discord.HTTPException as exc:
                log.error("Error sending farewell in %s: %s", guild.id, exc)

        roles = ", ".join(r.mention for r in member.roles if not r.is_default()) or "Ninguno"
        joined = discord_ts(member.joined_at) if member.joined_at else "Desconocido"
        if config.join_leave_log_channel_id:
            embed = discord.Embed(color=ERROR, timestamp=discord.utils.utcnow())
            embed.set_author(name="Miembro salio", icon_url=member.display_avatar.url)
            embed.add_field(name="Usuario", value=f"{member.name} ({member.id})", inline=True)
            embed.add_field(name="Se unio", value=joined, inline=True)
            embed.add_field(name="Roles", value=truncate(roles, 1024), inline=False)
            await send_to(guild, config.join_leave_log_channel_id, embed=embed)

        audit = discord.Embed(color=ERROR, title="📤 Miembro salió", timestamp=discord.utils.utcnow())
        audit.set_author(name=member.name, icon_url=member.display_avatar.url)
        audit.add_field(name="👤 Usuario", value=f"{member.mention} `{member.name}`", inline=True)
        audit.add_field(name="📅 Se unió", value=joined, inline=True)
        audit.add_field(name="🏷️ Roles", value=truncate(roles, 512), inline=False)
        audit.set_footer(text=f"ID: {member.id}")
        await send_audit(self.bot, guild, audit, fallback_channel_id=config.join_leave_log_channel_id,
                         already_sent=[config.join_leave_log_channel_id])

    async def _send_farewell(self, member: discord.Member, config: GuildConfig) -> None:
        guild = member.guild
        channel = text_channel(guild, config.farewell_channel_id)
        if channel is None:
            return
        inviter_mention, inviter_name = await self._inviter_of(guild, member.id, config)
        variables = _template_vars(member, guild, inviter_mention, mention=True)
        text = render_template(config.farewell_message or "Adiós {user}", variables)

        if config.farewell_image_enabled:
            try:
                png = await render_member_card(member, guild, config.farewell_card_layout, inviter_name)
                await channel.send(content=text, file=discord.File(io.BytesIO(png), filename="farewell.png"))
            except Exception:
                log.exception("Failed to generate farewell image")
                await channel.send(content=text)
            return

        footer = config.farewell_embed_footer or f"{guild.member_count} miembros restantes"
        embed = discord.Embed(
            color=parse_color(config.farewell_embed_color, ERROR),
            title=config.farewell_embed_title or "¡Adiós!",
            description=render_template(config.farewell_embed_description, variables)
            if config.farewell_embed_description else text,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=config.farewell_embed_thumbnail or member.display_avatar.with_size(256).url)
        embed.set_footer(text=render_template(footer, variables))
        if config.farewell_embed_image:
            embed.set_image(url=config.farewell_embed_image)
        await channel.send(embed=embed)

    # ── Dashboard preview ────────────────────────────────────────────────

    async def _preview_route(self, request: web.Request) -> web.Response:
        """Render a card exactly as the bot would, for the dashboard editor."""
        body = await read_json(request)
        guild = self.bot.get_guild(int(body.get("guildId") or 0))
        user = self.bot.get_user(int(body["userId"])) if body.get("userId") else None
        user = user or self.bot.user
        if guild is None or user is None:
            return web.json_response({"error": "Guild not available"}, status=404)
        png = await render_member_card(user, guild, body.get("layout"), body.get("inviterName") or "Invitador")
        return web.Response(body=png, content_type="image/png")


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(Members(bot))
