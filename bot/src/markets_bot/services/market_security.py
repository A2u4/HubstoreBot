"""Market registration security.

IP addresses are never stored: only a keyed HMAC of the normalized address,
used to detect sanction evasion. Optional VPN/proxy detection uses IPinfo.
The hashing must stay byte-compatible with v1 so existing blocks keep matching.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote, urlencode, urlsplit

import aiohttp
import discord
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from markets_bot.core.utils import utcnow
from markets_bot.db.base import camel_case
from markets_bot.db.models import (
    MarketNetworkBlock,
    MarketNetworkSignal,
    MarketRegistration,
    MarketVerificationSession,
)

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

SESSION_TTL = timedelta(minutes=10)
USED_SESSION_RETENTION = timedelta(hours=24)
TOKEN_ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")

Status = Literal["verificado", "bloqueado", "baneado", "vpn_bloqueada", "revision", "no_miembro", "desactivado", "error"]


# ─── Pure helpers ────────────────────────────────────────────────────────────


def registration_url(dashboard_url: str, identity: str) -> str:
    return f"{dashboard_url.rstrip('/')}/bots/{quote(identity)}/auth/registro"


def is_secure_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" or parts.hostname in ("localhost", "127.0.0.1", "::1")


def normalize_address(raw: str | None) -> tuple[str, int]:
    """First forwarded address, IPv4-mapped IPv6 unwrapped, IPv6 in canonical compressed form."""
    value = (raw or "").split(",")[0].strip().lower()
    value = value.removeprefix("[").split("]")[0] if value.startswith("[") else value
    value = value.split("%")[0]
    if value.startswith("::ffff:") and "." in value:
        value = value[7:]
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("No se pudo validar la red del registro") from exc
    return address.compressed, address.version


def hash_address(address: str, secret: str) -> str:
    if len(secret) < 32:
        raise ValueError("MARKET_IP_HASH_SECRET debe tener al menos 32 caracteres")
    return hmac.new(secret.encode(), address.encode(), hashlib.sha256).hexdigest()


@dataclass(slots=True)
class Privacy:
    status: Literal["clean", "anonymous", "hosting", "unavailable"]
    vpn: bool = False
    proxy: bool = False
    tor: bool = False
    relay: bool = False
    hosting: bool = False
    service: str = ""
    provider: str = "ipinfo"

    @property
    def flags(self) -> list[str]:
        names = (("VPN", self.vpn), ("proxy", self.proxy), ("Tor", self.tor), ("relay", self.relay),
                 ("hosting", self.hosting))
        return [name for name, on in names if on]


UNAVAILABLE = Privacy("unavailable")


def parse_ipinfo(body: Any) -> Privacy:
    data = body if isinstance(body, dict) else {}
    valid = all(isinstance(data.get(k), bool) for k in ("vpn", "proxy", "tor", "relay", "hosting"))
    vpn, proxy, tor, relay, hosting = (data.get(k) is True for k in ("vpn", "proxy", "tor", "relay", "hosting"))
    service = str(data.get("service") or "").strip()[:100] if isinstance(data.get("service"), str) else ""
    if not valid:
        status: Any = "unavailable"
    elif vpn or proxy or tor or relay:
        status = "anonymous"
    else:
        status = "hosting" if hosting else "clean"
    return Privacy(status, vpn, proxy, tor, relay, hosting, service)


async def inspect_privacy(address: str, version: int, token: str | None) -> Privacy:
    if not token:
        return UNAVAILABLE
    host = "v6.ipinfo.io" if version == 6 else "ipinfo.io"
    url = f"https://{host}/{quote(address)}/privacy?{urlencode({'token': token})}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as http, http.get(
            url, headers={"Accept": "application/json"}
        ) as resp:
            if resp.status != 200:
                return UNAVAILABLE
            return parse_ipinfo(await resp.json(content_type=None))
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return UNAVAILABLE


# ─── Service ─────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class RegistrationResult:
    blocked: bool
    block_source_user_id: str | None
    linked_user_ids: list[str]
    vpn_check_enabled: bool
    vpn_policy: str
    privacy: Privacy | None


class MarketSecurity:
    def __init__(self, bot: MarketsBot) -> None:
        self.bot = bot

    @property
    def url(self) -> str:
        settings = self.bot.settings
        return settings.market_registration_url or registration_url(settings.dashboard_url, settings.identity)

    @property
    def secure(self) -> bool:
        return is_secure_url(self.url)

    def _secret(self) -> str:
        secret = self.bot.settings.market_ip_hash_secret
        if secret is None:
            raise ValueError("MARKET_IP_HASH_SECRET no está configurado")
        return secret.get_secret_value()

    # Sessions (single-use links that expire in 10 minutes)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def create_session(self, guild_id: int, user_id: int, username: str) -> str:
        if str(guild_id) != self.bot.settings.guild_id:
            raise ValueError("El servidor no corresponde a esta instancia del bot")
        now = utcnow()
        token = secrets.token_urlsafe(32)
        async with self.bot.db.session() as session:
            await session.execute(delete(MarketVerificationSession).where(
                (MarketVerificationSession.expires_at < now)
                | (MarketVerificationSession.used_at.is_not(None)
                   & (MarketVerificationSession.created_at < now - USED_SESSION_RETENTION))
            ))
            session.add(MarketVerificationSession(
                token_hash=self._token_hash(token), guild_id=str(guild_id), user_id=str(user_id),
                username=username, expires_at=now + SESSION_TTL,
            ))
        return f"{self.url}?{urlencode({'sesion': token})}"

    async def claim_session(self, token: Any) -> MarketVerificationSession | None:
        if not isinstance(token, str) or not 40 <= len(token) <= 100 or not set(token) <= TOKEN_ALPHABET:
            return None
        now = utcnow()
        async with self.bot.db.session() as session:
            row = (await session.execute(select(MarketVerificationSession).where(
                MarketVerificationSession.token_hash == self._token_hash(token)
            ))).scalar_one_or_none()
            if row is None or row.guild_id != self.bot.settings.guild_id or row.used_at or row.expires_at <= now:
                return None
            claimed = await session.execute(update(MarketVerificationSession).where(
                MarketVerificationSession.id == row.id, MarketVerificationSession.used_at.is_(None),
                MarketVerificationSession.expires_at > now,
            ).values(used_at=now))
            if claimed.rowcount != 1:
                return None
            row.used_at = now
            return row

    async def release_session(self, row: MarketVerificationSession) -> None:
        async with self.bot.db.session() as session:
            await session.execute(update(MarketVerificationSession).where(
                MarketVerificationSession.id == row.id, MarketVerificationSession.used_at == row.used_at,
            ).values(used_at=None))

    # Registrations and network signals

    async def record(self, guild_id: str, user_id: str, username: str | None, raw_ip: str | None) -> RegistrationResult:
        address, version = normalize_address(raw_ip)
        ip_hash = hash_address(address, self._secret())
        now = utcnow()
        config = await self.bot.configs.get(guild_id)
        async with self.bot.db.session() as session:
            block = (await session.execute(select(MarketNetworkBlock).where(
                MarketNetworkBlock.guild_id == guild_id, MarketNetworkBlock.ip_hash == ip_hash
            ))).scalar_one_or_none()
        token = self.bot.settings.ipinfo_token
        privacy = (await inspect_privacy(address, version, token.get_secret_value() if token else None)
                   if config.market_vpn_check_enabled else None)

        async with self.bot.db.session() as session:
            registration_id = (await session.execute(
                insert(MarketRegistration).values(
                    guild_id=guild_id, user_id=user_id, username=username, accepted_privacy_at=now,
                ).on_conflict_do_update(
                    index_elements=["guildId", "userId"],
                    set_={"username": username, "acceptedPrivacyAt": now, "revokedAt": None, "lastSeenAt": now},
                ).returning(MarketRegistration.id)
            )).scalar_one()
            privacy_values: dict[str, Any] = {}
            if privacy is not None:
                privacy_values = {
                    "vpn_detected": privacy.vpn, "proxy_detected": privacy.proxy, "tor_detected": privacy.tor,
                    "relay_detected": privacy.relay, "hosting_detected": privacy.hosting,
                    "privacy_service": privacy.service or None, "privacy_provider": privacy.provider,
                    "privacy_checked_at": now,
                }
            stmt = insert(MarketNetworkSignal).values(
                guild_id=guild_id, user_id=user_id, registration_id=registration_id, ip_hash=ip_hash,
                ip_version=version, **privacy_values,
            )
            await session.execute(stmt.on_conflict_do_update(
                index_elements=["guildId", "userId", "ipHash"],
                set_={"registrationId": registration_id, "ipVersion": version, "lastSeenAt": now,
                      "seenCount": MarketNetworkSignal.seen_count + 1,
                      **{camel_case(k): v for k, v in privacy_values.items()}},
            ))
            linked = (await session.execute(select(MarketNetworkSignal.user_id).where(
                MarketNetworkSignal.guild_id == guild_id, MarketNetworkSignal.ip_hash == ip_hash,
                MarketNetworkSignal.user_id != user_id,
            ).distinct())).scalars().all()

            # Opportunistic retention cleanup; identifiers tied to active blocks are kept.
            retention = min(365, max(7, config.market_verification_retention_days))
            protected = select(MarketNetworkBlock.ip_hash).where(
                MarketNetworkBlock.guild_id == guild_id, MarketNetworkBlock.active.is_(True))
            await session.execute(delete(MarketNetworkSignal).where(
                MarketNetworkSignal.guild_id == guild_id,
                MarketNetworkSignal.last_seen_at < now - timedelta(days=retention),
                MarketNetworkSignal.ip_hash.not_in(protected),
            ))

        return RegistrationResult(
            blocked=bool(block and block.active), block_source_user_id=block.source_user_id if block else None,
            linked_user_ids=list(linked), vpn_check_enabled=config.market_vpn_check_enabled,
            vpn_policy="block" if config.market_vpn_policy == "block" else "review", privacy=privacy,
        )

    async def linked_accounts(self, guild_id: str, user_id: str) -> list[str]:
        async with self.bot.db.session() as session:
            hashes = select(MarketNetworkSignal.ip_hash).where(
                MarketNetworkSignal.guild_id == guild_id, MarketNetworkSignal.user_id == user_id)
            rows = (await session.execute(select(MarketNetworkSignal.user_id).where(
                MarketNetworkSignal.guild_id == guild_id, MarketNetworkSignal.ip_hash.in_(hashes),
                MarketNetworkSignal.user_id != user_id,
            ).distinct())).scalars().all()
        return list(rows)

    async def block_networks(self, guild_id: str, user_id: str, reason: str | None) -> tuple[int, list[str]]:
        async with self.bot.db.session() as session:
            hashes = (await session.execute(select(MarketNetworkSignal.ip_hash).where(
                MarketNetworkSignal.guild_id == guild_id, MarketNetworkSignal.user_id == user_id
            ).distinct())).scalars().all()
            for ip_hash in hashes:
                await session.execute(insert(MarketNetworkBlock).values(
                    guild_id=guild_id, ip_hash=ip_hash, source_user_id=user_id, reason=reason, active=True,
                ).on_conflict_do_update(
                    index_elements=["guildId", "ipHash"],
                    set_={"sourceUserId": user_id, "reason": reason, "active": True, "updatedAt": utcnow()},
                ))
        return len(hashes), await self.linked_accounts(guild_id, user_id)

    async def unblock_networks(self, guild_id: str, user_id: str) -> int:
        async with self.bot.db.session() as session:
            result = await session.execute(update(MarketNetworkBlock).where(
                MarketNetworkBlock.guild_id == guild_id, MarketNetworkBlock.source_user_id == user_id,
                MarketNetworkBlock.active.is_(True),
            ).values(active=False))
        return result.rowcount

    async def stats(self, guild_id: str) -> tuple[int, int]:
        async with self.bot.db.session() as session:
            registrations = await session.scalar(select(func.count()).select_from(MarketRegistration).where(
                MarketRegistration.guild_id == guild_id, MarketRegistration.revoked_at.is_(None)))
            blocks = await session.scalar(select(func.count()).select_from(MarketNetworkBlock).where(
                and_(MarketNetworkBlock.guild_id == guild_id, MarketNetworkBlock.active.is_(True))))
        return registrations or 0, blocks or 0

    # Full verification flow (called by the dashboard registration page)

    async def _log(self, guild: discord.Guild, channel_id: str | None, title: str, description: str, color: int) -> None:
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=discord.Embed(title=title, description=description, color=color,
                                                       timestamp=discord.utils.utcnow()),
                                   allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as exc:
                log.warning("Market registration log failed: %s", exc)

    @staticmethod
    def _protected(guild: discord.Guild, member: discord.Member) -> bool:
        """Staff, bots and the owner are never auto-banned by a network match."""
        perms = member.guild_permissions
        return member.bot or member.id == guild.owner_id or perms.administrator or perms.manage_guild or perms.ban_members

    async def complete(self, token: Any, raw_ip: str | None) -> Status:
        row = await self.claim_session(token)
        if row is None:
            return "error"
        try:
            return await self._complete(row, raw_ip)
        except Exception:
            await self.release_session(row)
            log.exception("Market verification failed")
            return "error"

    async def _complete(self, row: MarketVerificationSession, raw_ip: str | None) -> Status:
        guild = self.bot.get_guild(int(row.guild_id))
        config = await self.bot.configs.get(row.guild_id)
        if guild is None or not config.market_verification_enabled:
            return "desactivado"
        try:
            member = guild.get_member(int(row.user_id)) or await guild.fetch_member(int(row.user_id))
        except discord.NotFound:
            return "no_miembro"
        result = await self.record(row.guild_id, row.user_id, row.username, raw_ip)
        log_channel = config.market_verification_log_channel_id
        uid = row.user_id

        if result.blocked:
            risky = result.vpn_check_enabled and (result.privacy is None or result.privacy.status != "clean")
            protected = self._protected(guild, member)
            auto_banned = False
            if config.market_blocked_network_action == "ban" and not risky and not protected:
                try:
                    await guild.ban(member, reason="Coincidencia exacta con una red sancionada", delete_message_seconds=0)
                    auto_banned = True
                except discord.HTTPException:
                    auto_banned = False
            description = f"La cuenta <@{uid}> (`{uid}`) coincidió con una red asociada a una sanción activa."
            if result.block_source_user_id:
                description += f"\nSanción de origen: <@{result.block_source_user_id}> (`{result.block_source_user_id}`)"
            if protected:
                description += "\nNo se aplicó ban automático porque la cuenta tiene permisos protegidos."
            if risky:
                description += ("\nNo se aplicó ban automático porque la red requiere revisión "
                                "(VPN, proxy, hosting o detector no disponible).")
            await self._log(guild, log_channel, "Cuenta bloqueada automáticamente" if auto_banned
                            else "Registro bloqueado por seguridad", description, 0xD95C5C)
            return "baneado" if auto_banned else "bloqueado"

        if result.vpn_check_enabled:
            privacy = result.privacy
            if privacy is None or privacy.status == "unavailable":
                await self._log(guild, log_channel, "Verificación pendiente: detector no disponible",
                                f"La cuenta <@{uid}> (`{uid}`) completó OAuth, pero el servicio de análisis de red "
                                "no respondió.", 0xD98D3F)
                return "revision"
            if privacy.status in ("anonymous", "hosting"):
                rejected = result.vpn_policy == "block" and privacy.status == "anonymous"
                details = f"Cuenta: <@{uid}> (`{uid}`)\nSeñales: **{', '.join(privacy.flags) or 'red anónima'}**"
                if privacy.service:
                    details += f"\nServicio detectado: **{privacy.service}**"
                await self._log(guild, log_channel, "Verificación rechazada por red anónima" if rejected
                                else "Verificación pendiente por riesgo de red", details, 0xD98D3F)
                return "vpn_bloqueada" if rejected else "revision"

        if config.market_verification_role_id:
            await member.add_roles(discord.Object(int(config.market_verification_role_id)),
                                   reason="Verificación segura del Market")
        linked = ""
        if result.linked_user_ids:
            linked = "\nCoincidencias históricas para revisión: " + ", ".join(
                f"<@{i}>" for i in result.linked_user_ids[:10])
        await self._log(guild, log_channel, "Usuario verificado en el Market",
                        f"<@{uid}> (`{uid}`) completó el registro.{linked}", 0x2F9E66)
        return "verificado"
