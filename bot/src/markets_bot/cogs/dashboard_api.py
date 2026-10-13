"""Internal endpoints for the Next.js dashboard.

The dashboard reads and writes the database directly through Prisma. It calls
these routes only for things that need the live Discord connection: listing
channels, roles and members, sending messages, syncing commands, and telling
the bot that a config row changed.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands

from markets_bot.bot import MarketsBot
from markets_bot.core.command_sync import sync_guild
from markets_bot.core.tree import command_extras
from markets_bot.core.utils import INFO, parse_color
from markets_bot.web.internal_server import HttpError, json_response, read_json, require

log = logging.getLogger(__name__)

CHANNEL_TYPES = {discord.ChannelType.text, discord.ChannelType.voice, discord.ChannelType.category,
                 discord.ChannelType.news, discord.ChannelType.forum, discord.ChannelType.stage_voice}


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value if urlparse(value).scheme in {"http", "https"} else None


def build_embed(data: dict[str, Any]) -> discord.Embed:
    """Build an embed from the dashboard's message-sender payload, enforcing Discord's limits."""
    limits = {"title": 256, "description": 4096, "authorName": 256, "footerText": 2048}
    for key, limit in limits.items():
        if len(str(data.get(key) or "")) > limit:
            raise HttpError(400, f"{key} supera {limit} caracteres")
    fields = data.get("fields") or []
    if not isinstance(fields, list) or len(fields) > 25:
        raise HttpError(400, "Máximo 25 campos por embed")

    embed = discord.Embed(title=data.get("title") or None, description=data.get("description") or None,
                          color=parse_color(data.get("color"), INFO), url=_safe_url(data.get("titleUrl")))
    author = data.get("authorName") or data.get("author")
    if author:
        embed.set_author(name=author, icon_url=_safe_url(data.get("authorIconUrl")))
    footer = data.get("footerText") or data.get("footer")
    if footer:
        embed.set_footer(text=footer, icon_url=_safe_url(data.get("footerIconUrl")))
    if image := _safe_url(data.get("imageUrl") or data.get("image")):
        embed.set_image(url=image)
    if thumbnail := _safe_url(data.get("thumbnailUrl") or data.get("thumbnail")):
        embed.set_thumbnail(url=thumbnail)
    if data.get("timestamp"):
        embed.timestamp = discord.utils.utcnow()
    for index, field in enumerate(fields, 1):
        name, value = str(field.get("name") or ""), str(field.get("value") or "")
        if not name or not value:
            raise HttpError(400, f"El campo {index} necesita nombre y valor")
        if len(name) > 256 or len(value) > 1024:
            raise HttpError(400, f"El campo {index} supera los límites de Discord")
        embed.add_field(name=name, value=value, inline=bool(field.get("inline")))
    return embed


def _describe_command(command: app_commands.Command[Any, ..., Any] | app_commands.Group) -> list[dict[str, Any]]:
    """Flatten a command into dashboard rows: one per leaf, keyed like CommandPermission ("root leaf")."""
    extras = command_extras(command)
    default = command.default_permissions
    base = {"module": extras.get("module") or "utility",
            "adminOnlyByDefault": bool(default and default.administrator),
            "defaultPermissions": str(default.value) if default else None}
    if not isinstance(command, app_commands.Group):
        return [{"name": command.name, "description": command.description, **base}]
    rows = []
    for child in command.commands:
        leaves = child.commands if isinstance(child, app_commands.Group) else [child]
        for leaf in leaves:
            rows.append({"name": f"{command.name} {child.name}", "parent": command.name, "subcommand": child.name,
                         "description": leaf.description or f"{command.description} — {child.name}", **base})
    return rows


class DashboardApi(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self.started = time.time()
        route = bot.internal.route
        route("POST", "/internal/cache/invalidate")(self.invalidate)
        route("GET", "/internal/guilds")(self.guilds)
        route("GET", "/internal/guilds/{guild_id}/overview")(self.overview)
        route("GET", "/internal/guilds/{guild_id}/channels")(self.channels)
        route("GET", "/internal/guilds/{guild_id}/roles")(self.roles)
        route("GET", "/internal/guilds/{guild_id}/emojis")(self.emojis)
        route("GET", "/internal/guilds/{guild_id}/members")(self.members)
        route("GET", "/internal/guilds/{guild_id}/commands")(self.commands_list)
        route("POST", "/internal/guilds/{guild_id}/commands/sync")(self.commands_sync)
        route("POST", "/internal/guilds/{guild_id}/messages/send")(self.send_message)
        route("POST", "/internal/guilds/{guild_id}/welcome/test")(self.welcome_test)

    def _guild(self, request: web.Request) -> discord.Guild:
        raw = request.match_info.get("guild_id", "")
        guild = self.bot.get_guild(int(raw)) if raw.isdigit() else None
        if guild is None:
            raise HttpError(404, "El bot no está en ese servidor")
        return guild

    # ── Cache ────────────────────────────────────────────────────────────

    async def invalidate(self, request: web.Request) -> web.Response:
        """Called after the dashboard writes config/permissions. ``resync`` redeploys commands too."""
        body = await read_json(request)
        guild_id = str(body.get("guildId") or "") or None
        self.bot.configs.invalidate(guild_id)
        self.bot.tree.invalidate_permissions()  # type: ignore[attr-defined]
        self.bot.dispatch("cache_invalidate", guild_id)
        synced = None
        if body.get("resync") and guild_id and guild_id.isdigit() and self.bot.get_guild(int(guild_id)):
            synced = await sync_guild(self.bot, int(guild_id))
        return json_response({"ok": True, "synced": synced})

    # ── Guild data ───────────────────────────────────────────────────────

    async def guilds(self, _request: web.Request) -> web.Response:
        return json_response([{"id": str(g.id), "name": g.name, "icon": g.icon.url if g.icon else None,
                               "memberCount": g.member_count} for g in self.bot.guilds])

    async def overview(self, request: web.Request) -> web.Response:
        guild = self._guild(request)
        members = guild.members
        return json_response({
            "id": str(guild.id), "name": guild.name, "icon": guild.icon.url if guild.icon else None,
            "banner": guild.banner.url if guild.banner else None, "memberCount": guild.member_count,
            "humans": sum(1 for m in members if not m.bot), "bots": sum(1 for m in members if m.bot),
            "online": sum(1 for m in members if m.status is not discord.Status.offline),
            "channels": len(guild.channels), "roles": len(guild.roles) - 1, "emojis": len(guild.emojis),
            "boosts": guild.premium_subscription_count or 0, "boostTier": guild.premium_tier,
            "createdAt": guild.created_at.isoformat(), "ownerId": str(guild.owner_id),
            "bot": {"identity": self.bot.identity, "name": self.bot.user.name if self.bot.user else None,
                    "avatar": self.bot.user.display_avatar.url if self.bot.user else None,
                    "latencyMs": round(self.bot.latency * 1000) if self.bot.latency == self.bot.latency else None,
                    "uptimeSeconds": int(time.time() - self.started), "guilds": len(self.bot.guilds)},
        })

    async def channels(self, request: web.Request) -> web.Response:
        guild = self._guild(request)
        rows = [{"id": str(c.id), "name": c.name, "type": c.type.value, "position": c.position,
                 "parentId": str(c.category_id) if c.category_id else None}
                for c in guild.channels if c.type in CHANNEL_TYPES]
        return json_response(sorted(rows, key=lambda c: c["position"]))

    async def roles(self, request: web.Request) -> web.Response:
        guild = self._guild(request)
        me = guild.me
        return json_response([{"id": str(r.id), "name": r.name, "color": r.color.value, "position": r.position,
                               "managed": r.managed, "assignable": bool(me and r < me.top_role and not r.managed)}
                              for r in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()])

    async def emojis(self, request: web.Request) -> web.Response:
        guild = self._guild(request)
        return json_response([{"id": str(e.id), "name": e.name, "animated": e.animated, "url": e.url}
                              for e in guild.emojis])

    async def members(self, request: web.Request) -> web.Response:
        guild = self._guild(request)
        query = request.query.get("q", "").strip().lower()
        ids = {i for i in request.query.get("ids", "").split(",") if i.isdigit()}
        limit = min(int(request.query.get("limit", "25") or 25), 100)
        found = []
        for member in guild.members:
            if ids and str(member.id) not in ids:
                continue
            if query and query not in member.name.lower() and query not in member.display_name.lower() \
                    and query != str(member.id):
                continue
            found.append({"id": str(member.id), "name": member.name, "displayName": member.display_name,
                          "avatar": member.display_avatar.with_size(64).url, "bot": member.bot})
            if len(found) >= limit:
                break
        return json_response(found)

    # ── Commands ─────────────────────────────────────────────────────────

    async def commands_list(self, request: web.Request) -> web.Response:
        self._guild(request)
        rows = [row for command in self.bot.tree.get_commands(type=discord.AppCommandType.chat_input)
                for row in _describe_command(command)]
        return json_response(sorted(rows, key=lambda r: r["name"]))

    async def commands_sync(self, request: web.Request) -> web.Response:
        guild = self._guild(request)
        self.bot.configs.invalidate(guild.id)
        count = await sync_guild(self.bot, guild.id)
        return json_response({"success": True, "count": count, "message": "Comandos sincronizados con Discord"})

    # ── Messages ─────────────────────────────────────────────────────────

    async def send_message(self, request: web.Request) -> web.Response:
        guild = self._guild(request)
        body = await read_json(request)
        require(body, "channelId")
        content, embed_data = body.get("content"), body.get("embed")
        if not content and not embed_data:
            raise HttpError(400, "At least content or embed is required")
        channel = guild.get_channel_or_thread(int(body["channelId"])) if str(body["channelId"]).isdigit() else None
        if not isinstance(channel, discord.abc.Messageable):
            raise HttpError(404, "Canal no encontrado en este servidor")  # v1 accepted any channel id the bot could see
        embed = build_embed(embed_data) if isinstance(embed_data, dict) else None
        message = await channel.send(content=content or None, embed=embed,
                                     allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True))
        return json_response({"id": str(message.id), "channelId": str(channel.id)})

    async def welcome_test(self, request: web.Request) -> web.Response:
        """Post a real welcome/farewell message in the configured channel using a given member."""
        guild = self._guild(request)
        body = await read_json(request)
        members_cog = self.bot.get_cog("Members")
        if members_cog is None:
            raise HttpError(503, "Members module not loaded")
        user_id = str(body.get("userId") or "")
        member = (guild.get_member(int(user_id)) if user_id.isdigit() else None) or guild.me
        config = await self.bot.configs.get(guild.id)
        kind = body.get("kind", "welcome")
        channel_id = config.farewell_channel_id if kind == "farewell" else config.welcome_channel_id
        if not channel_id:
            raise HttpError(400, "No hay canal configurado")
        if kind == "farewell":
            await members_cog._send_farewell(member, config)  # type: ignore[attr-defined]
        else:
            await members_cog._send_welcome(member, config, "Dashboard", "Dashboard")  # type: ignore[attr-defined]
        return json_response({"success": True, "message": "Mensaje de prueba enviado"})


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(DashboardApi(bot))
