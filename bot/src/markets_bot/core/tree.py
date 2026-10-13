"""Command tree with the cluster's permission layers.

Every slash command passes, in order:

1. **Cooldown** – per user and command (``extras["cooldown"]`` seconds, default 3).
2. **Discord permissions** – ``extras["permissions"]`` (e.g. ``["ban_members"]``).
3. **Module** – ``extras["module"]`` must be enabled for the guild; non-public
   commands also respect the dashboard's per-module role restrictions.
   ``extras["always_on"]`` keeps a command usable while its module is off
   (v1 behaviour of ``/rep``, which was never gated by the reputation toggle).
4. **Command permission** – a dashboard ``CommandPermission`` row (keyed
   ``"<root> <leaf>"`` first, then ``"<root>"``) can disable a command or limit
   it to roles. A row without roles means admin-only.

Metadata lives in ``extras`` of the command or any of its parent groups.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from sqlalchemy import select

from markets_bot.core.cache import TtlCache
from markets_bot.core.errors import UserError
from markets_bot.core.guild_config import GuildConfigService
from markets_bot.db.models import CommandPermission

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

# Commands (or "command subcommand") anyone may use regardless of role restrictions.
PUBLIC_COMMANDS = frozenset(
    {
        "comprar",
        "perfil",
        "rep",
        "reputacion dar",
        "reputacion ranking",
        "reputacion ver",
        "reputacion recibir",
        "invitacion",
        "cotizacion",
        "verificar",
        "server",
        "servidor",
    }
)

AnyCommand = app_commands.Command[Any, ..., Any] | app_commands.Group


def command_extras(command: AnyCommand | None) -> dict[str, Any]:
    """Merge ``extras`` from the root group down to the leaf (leaf wins)."""
    chain: list[AnyCommand] = []
    node: AnyCommand | None = command
    while node is not None:
        chain.append(node)
        node = node.parent
    merged: dict[str, Any] = {}
    for item in reversed(chain):
        merged.update(item.extras)
    return merged


def permission_keys(command: AnyCommand) -> tuple[str, str | None]:
    """(``"root leaf"`` or ``"root"``, fallback ``"root"``) matching the legacy dashboard keys."""
    root = command.root_parent
    if root is None:
        return command.name, None
    return f"{root.name} {command.name}", root.name


def is_public(command: AnyCommand, extras: dict[str, Any]) -> bool:
    if extras.get("public"):
        return True
    key, root = permission_keys(command)
    return key in PUBLIC_COMMANDS or (root is None and command.name in PUBLIC_COMMANDS)


def _member_role_ids(interaction: discord.Interaction) -> set[int]:
    member = interaction.user
    return {r.id for r in member.roles} if isinstance(member, discord.Member) else set()


def _existing_roles(guild: discord.Guild | None, role_ids: list[str]) -> list[int]:
    if guild is None:
        return []
    result = []
    for rid in role_ids:
        if rid.isdigit() and guild.get_role(int(rid)):
            result.append(int(rid))
    return result


class MarketsCommandTree(app_commands.CommandTree["MarketsBot"]):
    def __init__(self, client: MarketsBot) -> None:
        super().__init__(client)
        self._cooldowns: dict[str, float] = {}
        self._perm_cache: TtlCache[tuple[bool, list[str]] | bool] = TtlCache(30, 2_000)

    # ── Layer helpers ────────────────────────────────────────────────────

    def _check_cooldown(self, interaction: discord.Interaction, name: str, seconds: float) -> float:
        now = time.monotonic()
        key = f"{name}:{interaction.user.id}"
        expires = self._cooldowns.get(key, 0)
        if now < expires:
            return expires - now
        self._cooldowns[key] = now + seconds
        if len(self._cooldowns) > 5_000:  # drop stale entries
            self._cooldowns = {k: v for k, v in self._cooldowns.items() if v > now}
        return 0

    async def _command_permission(self, guild_id: int, key: str) -> tuple[bool, list[str]] | None:
        cache_key = f"{guild_id}:{key}"
        cached = self._perm_cache.get(cache_key)
        if cached is not None:
            return None if cached is False else cached  # type: ignore[return-value]
        async with self.client.db.session() as session:
            row = (
                await session.execute(
                    select(CommandPermission).where(
                        CommandPermission.guild_id == str(guild_id), CommandPermission.command == key
                    )
                )
            ).scalar_one_or_none()
        value = (row.disabled, list(row.role_ids or [])) if row else None
        self._perm_cache.set(cache_key, value if value is not None else False)
        return value

    def invalidate_permissions(self) -> None:
        self._perm_cache.clear()

    # ── Global check ─────────────────────────────────────────────────────

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        command = interaction.command
        if not isinstance(command, app_commands.Command):
            return True
        extras = command_extras(command)
        bot = self.client

        remaining = self._check_cooldown(interaction, command.qualified_name, float(extras.get("cooldown", 3)))
        if remaining > 0:
            await _deny(
                interaction, f"Espera {remaining:.1f}s antes de usar `/{command.qualified_name}` de nuevo."
            )
            return False

        required: list[str] = extras.get("permissions", [])
        if required and interaction.guild is not None:
            perms = interaction.permissions
            if not all(getattr(perms, name, False) for name in required):
                await _deny(interaction, "No tienes permiso para usar este comando.")
                return False

        if interaction.guild is None:
            return True

        guild = interaction.guild
        public = is_public(command, extras)
        is_admin = interaction.permissions.administrator
        key, fallback = permission_keys(command)
        cmd_perm = await self._command_permission(guild.id, key)
        if cmd_perm is None and fallback:
            cmd_perm = await self._command_permission(guild.id, fallback)

        module = extras.get("module")
        if module and module != "config":
            config = await bot.configs.get(guild.id)
            if not extras.get("always_on") and not GuildConfigService.module_enabled(config, module):
                await _deny(
                    interaction,
                    f"El módulo **{module}** está desactivado. "
                    f"Actívalo con `/configuracion modulo activar name:{module}`.",
                )
                return False
            if not public and cmd_perm is None:
                configured = (config.module_allowed_roles or {}).get(module) or []
                allowed = _existing_roles(guild, configured)
                if allowed and not is_admin and not (_member_role_ids(interaction) & set(allowed)):
                    await _deny(interaction, f"No tienes permiso para usar comandos de **{module}**.")
                    return False

        if cmd_perm is not None:
            disabled, role_ids = cmd_perm
            if disabled:
                await _deny(interaction, "Este comando está desactivado en este servidor.")
                return False
            if not public:
                allowed = _existing_roles(guild, role_ids)
                if allowed:
                    if not is_admin and not (_member_role_ids(interaction) & set(allowed)):
                        roles = ", ".join(f"<@&{rid}>" for rid in allowed)
                        await _deny(interaction, f"Solo pueden usar este comando: {roles}")
                        return False
                elif not is_admin:
                    await _deny(interaction, "Este comando solo puede ser usado por administradores.")
                    return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, discord.NotFound) and original.code == 10062:
            log.warning("Interaction for /%s expired before we answered", _name(interaction))
            return
        if isinstance(original, UserError):
            await _deny(interaction, f"❌ {original}")
            return
        if isinstance(error, app_commands.CheckFailure):
            await _deny(interaction, "No tienes permiso para usar este comando.")
            return
        log.error("Error in /%s", _name(interaction), exc_info=original)
        await _deny(interaction, "Ocurrió un error al ejecutar este comando.")


def _name(interaction: discord.Interaction) -> str:
    return interaction.command.qualified_name if interaction.command else "?"


async def _deny(interaction: discord.Interaction, message: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException as exc:
        log.debug("Could not send denial message: %s", exc)
