"""Cross-bot sync: ban/unban events and the peer endpoints under ``/internal``.

The wire protocol is identical to v1 so old and new bots can coexist while the
cluster is migrated one bot at a time.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import discord
from aiohttp import web
from discord.ext import commands
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from markets_bot.bot import MarketsBot
from markets_bot.core.audit import mod_embed, send_audit, text_channel
from markets_bot.core.cache import TtlCache
from markets_bot.core.config import DISPLAY_NAMES
from markets_bot.core.dedupe import claim_side_effect, release_side_effect
from markets_bot.core.utils import WARN, aware, is_snowflake, utcnow
from markets_bot.db.models import GuildConfig, ModAction, Reputation, Warning
from markets_bot.db.serialize import to_wire
from markets_bot.services.moderation import invite_revocation
from markets_bot.services.moderation.state import pop_ban
from markets_bot.web.internal_server import HttpError, json_response, read_json, require

if TYPE_CHECKING:
    from markets_bot.cogs.invites import Invites
    from markets_bot.cogs.market_security import MarketSecurityCog

log = logging.getLogger(__name__)

BAN_DELETE_SECONDS = 7 * 86400
SYNC_TAG_RE = re.compile(r"^\[Sync from ([^\]]+)\]\s*", re.IGNORECASE)


def _parse_iso(value: Any) -> datetime:
    """ISO timestamp from a peer -> naive UTC (how Prisma stores DateTime)."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return utcnow()
    return parsed if parsed.tzinfo is None else parsed.astimezone(UTC).replace(tzinfo=None)


class ClusterSync(commands.Cog):
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot
        self._recent_announcements: TtlCache[bool] = TtlCache(5, 5_000)
        self._recent_cleanups: TtlCache[bool] = TtlCache(60, 5_000)
        route = bot.internal.route
        route("GET", "/internal/health")(self.health)
        route("POST", "/internal/bans")(self.peer_ban)
        route("POST", "/internal/unbans")(self.peer_unban)
        route("POST", "/internal/reps/count")(self.rep_count)
        route("POST", "/internal/reps/leaderboard")(self.rep_leaderboard)
        route("POST", "/internal/reps")(self.rep_ping)
        route("POST", "/internal/reps/migrate")(self.rep_migrate)
        route("POST", "/internal/moderation/warnings/query")(self.warnings_query)
        route("POST", "/internal/moderation/actions/query")(self.actions_query)
        route("POST", "/internal/moderation/warnings")(self.warning_sync)
        route("POST", "/internal/moderation/warnings/delete-user")(self.warnings_delete_user)
        route("POST", "/internal/moderation/warnings/delete-many")(self.warnings_delete_many)

    @property
    def self_guild_id(self) -> str:
        return self.bot.settings.guild_id

    # ── Ban events ───────────────────────────────────────────────────────

    async def _recent_synced(self, guild_id: int, user_id: int, action: str) -> ModAction | None:
        async with self.bot.db.session() as session:
            return (await session.execute(select(ModAction).where(
                ModAction.guild_id == str(guild_id), ModAction.user_id == str(user_id), ModAction.action == action,
                ModAction.synced_from_guild_id.is_not(None), ModAction.created_at >= utcnow() - timedelta(seconds=60),
            ).order_by(ModAction.created_at.desc()).limit(1))).scalar_one_or_none()

    async def _audit_ban_entry(self, guild: discord.Guild, user_id: int,
                               action: discord.AuditLogAction) -> tuple[int | None, str | None]:
        try:
            async for entry in guild.audit_logs(action=action, limit=5):
                if entry.target and entry.target.id == user_id:
                    return (entry.user.id if entry.user else None), entry.reason
        except discord.HTTPException as exc:
            log.warning("Audit log fetch failed: %s", exc)
        return None, None

    async def _user_name(self, user_id: int | None) -> tuple[str | int | None, str]:
        if not user_id:
            return None, "Desconocido"
        user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except discord.HTTPException:
                return user_id, "Desconocido"
        return user.id, user.name

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member) -> None:
        release_side_effect(f"unban:{guild.id}:{user.id}")
        if not claim_side_effect(f"ban:{guild.id}:{user.id}"):
            return
        config = await self.bot.configs.get(guild.id)

        market_blocked, market_linked = 0, []
        market_cog: MarketSecurityCog | None = self.bot.get_cog("MarketSecurity")  # type: ignore[assignment]
        if config.market_verification_enabled and market_cog is not None:
            try:
                market_blocked, market_linked = await market_cog.market.block_networks(
                    str(guild.id), str(user.id), "Ban activo en Discord")
            except Exception as exc:
                log.warning("Market network block failed for %s: %s", user.id, exc)

        try:
            revocation = await invite_revocation.revoke_for_banned_user(guild, user.id)
            if revocation.revoked:
                log.info("Revoked %d invite(s) created by banned user %s", revocation.revoked, user.id)
        except discord.HTTPException as exc:
            log.warning("Invite revocation failed for %s: %s", user.id, exc)

        recent = await self._recent_synced(guild.id, user.id, "ban")
        pending = pop_ban(user.id, guild.id)
        if pending:
            moderator_id: int | None = int(pending.moderator_id)
            reason = pending.reason
        else:
            moderator_id, reason = await self._audit_ban_entry(guild, user.id, discord.AuditLogAction.ban)

        sync_tag = SYNC_TAG_RE.match(reason or "")
        recent_reason = SYNC_TAG_RE.sub("", recent.reason if recent else "").strip() or None
        clean_reason = SYNC_TAG_RE.sub("", reason or "").strip() or recent_reason

        # Manual bans (Discord UI, other bots) also get 7 days of message cleanup.
        if not (pending and pending.delete_messages_applied) and self._recent_cleanups.claim(f"{guild.id}:{user.id}"):
            try:
                await guild.ban(user, reason=clean_reason or "Baneo con limpieza automática de mensajes",
                                delete_message_seconds=BAN_DELETE_SECONDS)
            except discord.HTTPException as exc:
                log.warning("Ban message cleanup failed: %s", exc)

        is_synced = recent is not None or sync_tag is not None
        origin = None
        if is_synced:
            origin = (recent.synced_from_guild_name if recent else None) or (
                DISPLAY_NAMES.get(sync_tag.group(1).lower().strip(), sync_tag.group(1)) if sync_tag else None)
            if recent and recent.moderator_id not in ("system", "unknown") and is_snowflake(recent.moderator_id):
                moderator_id = int(recent.moderator_id)
        announce = self._recent_announcements.claim(f"{guild.id}:{user.id}")

        extra: list[tuple[str, str, bool]] = []
        if market_blocked:
            extra.append(("Seguridad del Market", f"{market_blocked} identificador(es) de red bloqueado(s). "
                          f"{len(market_linked)} cuenta(s) relacionada(s) requieren revisión manual.", False))
        invites_cog: Invites | None = self.bot.get_cog("Invites")  # type: ignore[assignment]
        record = await invites_cog.last_invite_for(guild.id, user.id) if invites_cog else None
        if record and invites_cog:
            inviter_id, _ = await self._user_name(int(record.inviter_id))
            banned = await invites_cog.banned_invitees(guild.id, record.inviter_id)
            inviter = f"<@{record.inviter_id}> (`{record.inviter_id}`)" if inviter_id else f"`{record.inviter_id}`"
            extra += [
                ("Invitado por", inviter, True),
                ("Codigo invite", f"`{record.code}`", True),
                ("Invitados baneados por ese invitador", str(banned), True),
            ]

        log_channel_id = config.ban_log_channel_id or config.mod_log_channel_id
        if log_channel_id and announce:
            channel = text_channel(guild, log_channel_id)
            if channel is not None:
                mod_id, mod_name = await self._user_name(moderator_id)
                embed = mod_embed("ban", guild, user, mod_id, mod_name, reason=clean_reason,
                                  origin_guild_name=origin, extra=extra or None)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

        market_log = config.market_verification_log_channel_id
        if market_linked and market_log and market_log != log_channel_id and announce:
            channel = text_channel(guild, market_log)
            if channel is not None:
                listed = "\n".join(f"• <@{i}> (`{i}`)" for i in market_linked[:20])
                try:
                    await channel.send(embed=discord.Embed(
                        color=0xD98D3F, title="Cuentas relacionadas para revisión", timestamp=discord.utils.utcnow(),
                        description=f"El ban de <@{user.id}> bloqueó sus identificadores registrados. Estas cuentas "
                                    f"presentan coincidencias históricas:\n{listed}\n\nNo se banearon automáticamente "
                                    "porque una red compartida o VPN puede producir falsos positivos.",
                    ), allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    pass

        if is_synced:
            return
        async with self.bot.db.session() as session:
            own = await session.scalar(select(ModAction.id).where(
                ModAction.guild_id == str(guild.id), ModAction.user_id == str(user.id), ModAction.action == "ban",
                ModAction.synced_from_guild_id.is_(None), ModAction.created_at >= utcnow() - timedelta(seconds=60),
            ).limit(1))
            if own is None:
                session.add(ModAction(guild_id=str(guild.id), user_id=str(user.id),
                                      moderator_id=str(moderator_id or "unknown"), action="ban",
                                      reason=clean_reason or "Sin razón especificada"))
        if config.ban_sync_enabled:
            await self.bot.peers.broadcast("bans", {
                "userId": str(user.id), "reason": clean_reason, "fromGuildId": str(guild.id),
                "fromGuildName": guild.name, "fromBot": self.bot.identity,
                "moderatorId": str(moderator_id) if moderator_id else None,
            })

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        release_side_effect(f"ban:{guild.id}:{user.id}")
        if not claim_side_effect(f"unban:{guild.id}:{user.id}"):
            return
        recent = await self._recent_synced(guild.id, user.id, "unban")
        config = await self.bot.configs.get(guild.id)
        market_cog: MarketSecurityCog | None = self.bot.get_cog("MarketSecurity")  # type: ignore[assignment]
        if config.market_verification_enabled and market_cog is not None:
            try:
                await market_cog.market.unblock_networks(str(guild.id), str(user.id))
            except Exception as exc:
                log.warning("Market network unblock failed for %s: %s", user.id, exc)

        moderator_id, _ = await self._audit_ban_entry(guild, user.id, discord.AuditLogAction.unban)
        log_channel_id = config.ban_log_channel_id or config.mod_log_channel_id or config.audit_log_channel_id
        channel = text_channel(guild, log_channel_id)
        if channel is not None:
            mod_id, mod_name = await self._user_name(moderator_id)
            embed = mod_embed("unban", guild, user, mod_id, mod_name,
                              reason="Unban propagado desde otro servidor del cluster" if recent else None,
                              origin_guild_name=recent.synced_from_guild_name if recent else None)
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass
            await send_audit(self.bot, guild, embed, fallback_channel_id=log_channel_id, already_sent=[log_channel_id])
        if recent is None and config.ban_sync_enabled:
            await self.bot.peers.broadcast("unbans", {
                "userId": str(user.id), "fromGuildId": str(guild.id), "fromGuildName": guild.name,
                "fromBot": self.bot.identity, "moderatorId": str(moderator_id) if moderator_id else None,
            })

    # ── Peer endpoints ───────────────────────────────────────────────────

    def _require_self_guild(self) -> str:
        if not self.self_guild_id:
            raise HttpError(500, "Self guildId not configured")
        return self.self_guild_id

    async def _self_guild(self) -> discord.Guild | None:
        gid = int(self.self_guild_id)
        guild = self.bot.get_guild(gid)
        if guild is None:
            try:
                guild = await self.bot.fetch_guild(gid)
            except discord.HTTPException:
                return None
        return guild

    async def _config(self, guild_id: str) -> GuildConfig | None:
        async with self.bot.db.session() as session:
            return await session.get(GuildConfig, guild_id)

    async def health(self, _request: web.Request) -> web.Response:
        return json_response({"ok": True, "identity": self.bot.identity, "guildId": self.self_guild_id})

    async def peer_ban(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        require(body, "userId", "fromGuildId", "fromBot")
        gid = self._require_self_guild()
        config = await self._config(gid)
        if config is None or not config.ban_sync_enabled:
            return json_response({"skipped": True, "reason": "ban sync disabled"})
        reason = body.get("reason") or "Sin razón especificada"
        async with self.bot.db.session() as session:
            existing = await session.scalar(select(ModAction.id).where(
                ModAction.guild_id == gid, ModAction.user_id == str(body["userId"]), ModAction.action == "ban",
                ModAction.active.is_(True), ModAction.synced_from_guild_id == str(body["fromGuildId"]),
            ).limit(1))
            if existing:
                return json_response({"ok": True, "synced": False, "skipped": True, "reason": "already synced"})
            # Persist the marker before banning so the ban event recognizes it as synced.
            session.add(ModAction(
                guild_id=gid, user_id=str(body["userId"]), moderator_id=str(body.get("moderatorId") or "system"),
                action="ban", reason=reason, synced_from_guild_id=str(body["fromGuildId"]),
                synced_from_bot=str(body["fromBot"]), synced_from_guild_name=body.get("fromGuildName"),
            ))
        guild = await self._self_guild()
        if guild is None:
            log.warning("[internal/bans] guild %s not available", gid)
        else:
            try:
                await guild.ban(discord.Object(int(body["userId"])), reason=f"[Sync from {body['fromBot']}] {reason}"[:512],
                                delete_message_seconds=BAN_DELETE_SECONDS)
            except discord.HTTPException as exc:
                log.warning("[internal/bans] discord ban failed (maybe already banned): %s", exc)
        return json_response({"ok": True, "synced": True})

    async def peer_unban(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        require(body, "userId", "fromGuildId", "fromBot")
        gid = self._require_self_guild()
        config = await self._config(gid)
        if config is None or not config.ban_sync_enabled:
            return json_response({"skipped": True})
        guild = await self._self_guild()
        if guild is not None:
            try:
                await guild.unban(discord.Object(int(body["userId"])), reason=f"[Sync from {body['fromBot']}]")
            except discord.HTTPException as exc:
                log.warning("[internal/unbans] discord unban failed (maybe not banned): %s", exc)
        async with self.bot.db.session() as session:
            await session.execute(update(ModAction).where(
                ModAction.guild_id == gid, ModAction.user_id == str(body["userId"]), ModAction.action == "ban",
                ModAction.active.is_(True)).values(active=False))
            session.add(ModAction(
                guild_id=gid, user_id=str(body["userId"]), moderator_id=str(body.get("moderatorId") or "system"),
                action="unban", reason="Unban propagado", synced_from_guild_id=str(body["fromGuildId"]),
                synced_from_bot=str(body["fromBot"]), synced_from_guild_name=body.get("fromGuildName"),
            ))
        return json_response({"ok": True})

    async def rep_count(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        if not body.get("userId"):
            raise HttpError(400, "Missing userId")
        if not self.self_guild_id:
            return json_response({"count": 0})
        async with self.bot.db.session() as session:
            count = await session.scalar(select(func.count()).select_from(Reputation).where(
                Reputation.guild_id == self.self_guild_id, Reputation.user_id == str(body["userId"])))
        return json_response({"count": count or 0})

    async def rep_leaderboard(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        if not self.self_guild_id:
            return json_response({"rows": []})
        try:
            limit = min(max(int(body.get("limit") or 50), 1), 5000)
        except (TypeError, ValueError):
            limit = 50
        async with self.bot.db.session() as session:
            rows = (await session.execute(
                select(Reputation.user_id, func.count().label("n")).where(Reputation.guild_id == self.self_guild_id)
                .group_by(Reputation.user_id).order_by(func.count().desc()).limit(limit)
            )).all()
        return json_response({"rows": [{"userId": uid, "count": n} for uid, n in rows]})

    async def rep_ping(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        require(body, "userId", "giverId", "fromGuildId", "fromBot")
        config = await self._config(self._require_self_guild())
        if config is None or str(body["fromGuildId"]) not in (config.rep_sync_guild_ids or []):
            return json_response({"skipped": True, "reason": "rep sync not enabled for source guild"})
        # Reps are summed across guilds at read time; accepting the ping is enough.
        return json_response({"ok": True, "accepted": True})

    async def rep_migrate(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        require(body, "fromUserId", "toUserId", "fromGuildId")
        gid = self._require_self_guild()
        config = await self._config(gid)
        if config is None or str(body["fromGuildId"]) not in (config.rep_sync_guild_ids or []):
            return json_response({"skipped": True, "moved": 0, "reason": "rep sync not enabled for source guild"})
        async with self.bot.db.session() as session:
            result = await session.execute(update(Reputation).where(
                Reputation.guild_id == gid, Reputation.user_id == str(body["fromUserId"]),
            ).values(user_id=str(body["toUserId"]), reason=body.get("reason") or "migracion de reps"))
        return json_response({"ok": True, "moved": result.rowcount})

    async def _query(self, request: web.Request, model: type[Warning] | type[ModAction]) -> web.Response:
        body = await read_json(request)
        if not self.self_guild_id:
            return json_response({"rows": []})
        try:
            limit = min(max(int(body.get("limit") or 100), 1), 200)
        except (TypeError, ValueError):
            limit = 100
        stmt = select(model).where(model.guild_id == self.self_guild_id)
        if body.get("userId"):
            stmt = stmt.where(model.user_id == str(body["userId"]))
        async with self.bot.db.session() as session:
            rows = (await session.execute(stmt.order_by(model.created_at.desc()).limit(limit))).scalars().all()
        return json_response({"rows": [to_wire(r) for r in rows]})

    async def warnings_query(self, request: web.Request) -> web.Response:
        return await self._query(request, Warning)

    async def actions_query(self, request: web.Request) -> web.Response:
        return await self._query(request, ModAction)

    async def warning_sync(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        require(body, "id", "userId", "moderatorId", "fromGuildId", "fromBot")
        gid = self._require_self_guild()
        created_at = _parse_iso(body["createdAt"]) if body.get("createdAt") else utcnow()
        reason = body.get("reason") or "Sin razón proporcionada"
        common = {"synced_from_guild_id": str(body["fromGuildId"]), "synced_from_bot": str(body["fromBot"]),
                  "synced_from_guild_name": body.get("fromGuildName")}
        async with self.bot.db.session() as session:
            existed = await session.scalar(select(Warning.id).where(
                Warning.guild_id == gid, Warning.source_warning_id == str(body["id"])))
            warning_id = (await session.execute(insert(Warning).values(
                guild_id=gid, user_id=str(body["userId"]), moderator_id=str(body["moderatorId"]), reason=reason,
                source_warning_id=str(body["id"]), created_at=created_at, **common,
            ).on_conflict_do_update(index_elements=["guildId", "sourceWarningId"],
                                    set_={"reason": reason, "moderatorId": str(body["moderatorId"])})
              .returning(Warning.id))).scalar_one()
            if body.get("actionId"):
                await session.execute(insert(ModAction).values(
                    guild_id=gid, user_id=str(body["userId"]), moderator_id=str(body["moderatorId"]), action="warn",
                    reason=reason, source_action_id=str(body["actionId"]), created_at=created_at, **common,
                ).on_conflict_do_update(index_elements=["guildId", "sourceActionId"],
                                        set_={"reason": reason, "moderatorId": str(body["moderatorId"])}))

        if not existed:
            await self._announce_synced_warning(gid, body, reason, created_at)
        return json_response({"ok": True, "warningId": warning_id})

    async def _announce_synced_warning(self, gid: str, body: dict[str, Any], reason: str, created_at: datetime) -> None:
        guild = await self._self_guild()
        config = await self._config(gid)
        if guild is None or config is None:
            return
        channel = text_channel(guild, config.warn_log_channel_id or config.mod_log_channel_id
                               or config.audit_log_channel_id)
        if channel is None:
            return
        origin = body.get("fromGuildName") or body["fromBot"]
        target_id, target_name = await self._user_name(int(body["userId"]) if is_snowflake(str(body["userId"])) else None)
        moderator = str(body["moderatorId"])
        embed = discord.Embed(color=WARN, title="⚠️ Advertencia sincronizada",
                              description=f"**{target_name if target_id else body['userId']}** fue advertido en {origin}.",
                              timestamp=aware(created_at))
        embed.set_author(name=guild.name, icon_url=guild.icon.with_size(64).url if guild.icon else None)
        embed.add_field(name="Servidor origen", value=origin, inline=True)
        embed.add_field(name="Usuario", value=f"<@{body['userId']}>", inline=True)
        embed.add_field(name="Moderador", value=f"<@{moderator}>" if is_snowflake(moderator) else moderator, inline=True)
        embed.add_field(name="Razón", value=reason, inline=False)
        embed.set_footer(text="Registro conectado Vapiano ↔ HubStore")
        user = self.bot.get_user(target_id) if isinstance(target_id, int) else None
        if user:
            embed.set_thumbnail(url=user.display_avatar.with_size(128).url)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            log.warning("Synced warning log failed: %s", exc)

    async def warnings_delete_user(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        require(body, "userId", "fromGuildId", "fromBot")
        gid = self._require_self_guild()
        async with self.bot.db.session() as session:
            result = await session.execute(delete(Warning).where(
                Warning.guild_id == gid, Warning.user_id == str(body["userId"])))
        return json_response({"ok": True, "deleted": result.rowcount})

    async def warnings_delete_many(self, request: web.Request) -> web.Response:
        body = await read_json(request)
        raw_ids = body.get("warningIds")
        ids = list(dict.fromkeys(
            i for i in raw_ids if isinstance(i, str) and 0 < len(i) <= 64))[:100] if isinstance(raw_ids, list) else []
        if not body.get("userId") or not body.get("fromGuildId") or not body.get("fromBot") or not ids:
            raise HttpError(400, "Missing or invalid required fields")
        gid = self._require_self_guild()
        async with self.bot.db.session() as session:
            result = await session.execute(delete(Warning).where(
                Warning.guild_id == gid, Warning.user_id == str(body["userId"]),
                or_(Warning.id.in_(ids), Warning.source_warning_id.in_(ids))))
        return json_response({"ok": True, "deleted": result.rowcount})


async def setup(bot: MarketsBot) -> None:
    await bot.add_cog(ClusterSync(bot))
