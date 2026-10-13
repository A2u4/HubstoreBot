"""Revoking invite links: per user, for banned users, or the whole server (with confirmation)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

import discord

from markets_bot.core.cache import TtlCache
from markets_bot.core.utils import ERROR, INFO, OK, WARN
from markets_bot.services.moderation import admin_actions

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

CONFIRM_PREFIX = "mod_invite_revoke_confirm_"
CANCEL_PREFIX = "mod_invite_revoke_cancel_"
CONFIRMATION_TTL = timedelta(minutes=5)
DELETE_CONCURRENCY = 4

_recent_user_revocations: TtlCache[bool] = TtlCache(60, 10_000)
_active_invites: TtlCache[list[discord.Invite]] = TtlCache(10, 500)

Progress = Callable[[int, int], Awaitable[None]]


@dataclass(slots=True)
class RevocationResult:
    matched: int = 0
    revoked: int = 0
    failed: list[tuple[str, str, int | None]] = field(default_factory=list)  # (code, reason, inviter)
    skipped_recently: bool = False


def _clean(name: str) -> str:
    return "".join(c for c in name if c not in "`*_~|")


async def _active(guild: discord.Guild, force: bool) -> list[discord.Invite]:
    cached = _active_invites.get(str(guild.id))
    if cached is not None and not force:
        return list(cached)
    invites = await guild.invites()
    _active_invites.set(str(guild.id), invites)
    return list(invites)


async def _revoke_matching(
    guild: discord.Guild, predicate: Callable[[discord.Invite], bool], reason: str,
    *, force_fetch: bool = True, on_progress: Progress | None = None,
) -> RevocationResult:
    invites = await _active(guild, force_fetch)
    matching = [inv for inv in invites if predicate(inv)]
    result = RevocationResult(matched=len(matching))
    deleted: set[str] = set()
    processed = 0
    queue = list(matching)

    async def worker() -> None:
        nonlocal processed
        while queue:
            invite = queue.pop(0)
            try:
                await invite.delete(reason=reason[:500])
                deleted.add(invite.code)
            except discord.NotFound:
                deleted.add(invite.code)  # already gone: desired final state reached
            except discord.HTTPException as exc:
                result.failed.append((invite.code, str(exc)[:180], invite.inviter.id if invite.inviter else None))
            finally:
                processed += 1
                if on_progress:
                    await on_progress(processed, len(matching))

    await asyncio.gather(*(worker() for _ in range(min(DELETE_CONCURRENCY, max(1, len(matching))))))
    _active_invites.set(str(guild.id), [inv for inv in invites if inv.code not in deleted])
    result.revoked = len(deleted)
    return result


async def revoke_for_users(
    guild: discord.Guild, user_ids: Iterable[int | str], reason: str = "Invitaciones revocadas por moderación"
) -> RevocationResult:
    ids = {int(u) for u in user_ids}
    if not ids:
        return RevocationResult()
    result = await _revoke_matching(guild, lambda inv: bool(inv.inviter and inv.inviter.id in ids), reason)
    failed_creators = {f[2] for f in result.failed if f[2]}
    for uid in ids - failed_creators:
        _recent_user_revocations.set(f"{guild.id}:{uid}", True)
    return result


async def revoke_for_banned_user(guild: discord.Guild, user_id: int) -> RevocationResult:
    """Called on every ban. Skipped when the chain-ban flow already revoked this user's links."""
    if _recent_user_revocations.get(f"{guild.id}:{user_id}"):
        return RevocationResult(skipped_recently=True)
    result = await _revoke_matching(
        guild, lambda inv: bool(inv.inviter and inv.inviter.id == user_id),
        "Invitaciones revocadas automáticamente por baneo", force_fetch=False,
    )
    if not result.failed:
        _recent_user_revocations.set(f"{guild.id}:{user_id}", True)
    return result


def _channel_summary(invites: list[discord.Invite]) -> str:
    counts = Counter(f"<#{inv.channel.id}>" if inv.channel else "Canal desconocido" for inv in invites)
    lines = [f"• {channel}: {count}" for channel, count in counts.most_common(12)]
    if len(counts) > 12:
        lines.append(f"• …y {len(counts) - 12} canal(es) más")
    return "\n".join(lines) or "Sin canales"


async def prepare(bot: MarketsBot, interaction: discord.Interaction, scope: str, target: discord.User | None) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("Este comando solo funciona dentro de un servidor.", ephemeral=True)
        return
    if not interaction.permissions.administrator:
        await interaction.response.send_message("Solo los administradores pueden revocar invitaciones.", ephemeral=True)
        return
    if scope == "user" and target is None:
        await interaction.response.send_message(
            "Selecciona el `usuario` cuyas invitaciones deseas revocar.", ephemeral=True)
        return
    if scope == "server" and target is not None:
        await interaction.response.send_message(
            "Para el alcance `servidor` no debes seleccionar un usuario.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    invites = await _active(guild, True)
    matching = invites if scope == "server" else [
        inv for inv in invites if inv.inviter and target and inv.inviter.id == target.id
    ]
    if not matching:
        await interaction.edit_original_response(
            content="El servidor no tiene invitaciones activas que se puedan revocar." if scope == "server"
            else f"**{_clean(target.name if target else '')}** no tiene invitaciones activas.")
        return

    created = await admin_actions.create(
        bot.db, guild_id=str(guild.id), moderator_id=str(interaction.user.id), type_="invite-revocation",
        payload={"scope": scope, "userId": str(target.id) if target else None,
                 "userName": _clean(target.name) if target else None},
        total=len(matching), expires_in=CONFIRMATION_TTL,
    )
    if not created.created:
        await interaction.edit_original_response(content=(
            "Ya hay una revocación de invitaciones en curso en este servidor.\n"
            f"Progreso registrado: **{created.action.progress}/{created.action.total}**.\n"
            "Espera a que termine antes de iniciar otra."))
        return

    scope_text = ("todas las invitaciones activas del servidor" if scope == "server"
                  else f"las invitaciones creadas por **{_clean(target.name if target else '')}**")
    embed = discord.Embed(color=ERROR, title="Confirmar revocación de invitaciones",
                          description=f"Vas a revocar {scope_text}. Esta acción invalida los enlaces inmediatamente.",
                          timestamp=discord.utils.utcnow())
    embed.add_field(name="Invitaciones encontradas", value=str(len(matching)), inline=True)
    embed.add_field(name="Alcance", value="Todo el servidor" if scope == "server" else "Un usuario", inline=True)
    embed.add_field(name="Canales afectados", value=_channel_summary(matching), inline=False)
    embed.set_footer(text="La confirmación expira en 5 minutos. El historial interno no será eliminado.")
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=f"Revocar {len(matching)} invitación(es)", style=discord.ButtonStyle.danger,
                                    custom_id=f"{CONFIRM_PREFIX}{created.action.id}"))
    view.add_item(discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary,
                                    custom_id=f"{CANCEL_PREFIX}{created.action.id}"))
    await interaction.edit_original_response(embed=embed, view=view,
                                             allowed_mentions=discord.AllowedMentions.none())


async def handle_button(bot: MarketsBot, interaction: discord.Interaction) -> None:
    custom_id = str((interaction.data or {}).get("custom_id", ""))
    is_confirm = custom_id.startswith(CONFIRM_PREFIX)
    guild = interaction.guild
    if not interaction.permissions.administrator:
        await interaction.response.send_message("Ya no tienes permisos para confirmar esta acción.", ephemeral=True)
        return
    if guild is None:
        await interaction.response.send_message("Esta acción solo funciona dentro de un servidor.", ephemeral=True)
        return
    action_id = custom_id.removeprefix(CONFIRM_PREFIX if is_confirm else CANCEL_PREFIX)
    await interaction.response.defer()
    edit = interaction.edit_original_response

    if not is_confirm:
        outcome = await admin_actions.cancel(bot.db, action_id=action_id, type_="invite-revocation",
                                             guild_id=str(guild.id), moderator_id=str(interaction.user.id))
        text = {"cancelled": "Revocación cancelada. No se eliminó ninguna invitación.",
                "replaced": "Esta confirmación fue reemplazada por una más reciente."}.get(
            outcome, "Esta confirmación ya no está pendiente.")
        await edit(content=text, embed=None, view=None)
        return

    claimed = await admin_actions.claim(bot.db, action_id=action_id, type_="invite-revocation",
                                        guild_id=str(guild.id), moderator_id=str(interaction.user.id))
    if claimed.outcome != "claimed" or claimed.action is None:
        text = {
            **admin_actions.OUTCOME_TEXT,
            "expired": "Esta confirmación expiró. Ejecuta nuevamente `/revocar-invitaciones`.",
            "running": "Esta revocación ya está en curso.",
            "completed": "Esta revocación ya finalizó.",
            "cancelled": "Esta revocación fue cancelada.",
            "moderator-mismatch": "Solo el administrador que preparó la revocación puede confirmarla.",
        }.get(claimed.outcome, "Esta confirmación ya no se puede ejecutar.")
        await edit(content=text, embed=None, view=None)
        return

    action = claimed.action
    payload = action.payload or {}
    if payload.get("scope") not in ("server", "user"):
        await admin_actions.finish(bot.db, action.id, "failed", {"reason": "Payload inválido"},
                                   "La acción guardada no contiene un alcance válido.")
        await edit(content="La confirmación guardada es inválida.", embed=None, view=None)
        return

    def progress_embed(done: int, total: int) -> discord.Embed:
        embed = discord.Embed(color=INFO, title="Revocando invitaciones", timestamp=discord.utils.utcnow(),
                              description="Discord limita la velocidad de eliminación. El bot continuará de forma "
                                          "segura hasta terminar.")
        embed.add_field(name="Procesadas", value=f"{done}/{total}", inline=True)
        embed.add_field(name="Estado", value="Finalizando" if done >= total else "En curso", inline=True)
        embed.set_footer(text="No ejecutes otra revocación mientras esta operación esté activa.")
        return embed

    await edit(embed=progress_embed(0, action.total), view=None, allowed_mentions=discord.AllowedMentions.none())
    last_stored, last_ui = 0, 0.0

    async def on_progress(done: int, total: int) -> None:
        nonlocal last_stored, last_ui
        if done == total or done - last_stored >= 10:
            last_stored = done
            await admin_actions.progress(bot.db, action.id, done, total)
        now = time.monotonic()
        if done == total or now - last_ui >= 2.5:
            last_ui = now
            try:
                await edit(embed=progress_embed(done, total), view=None)
            except discord.HTTPException as exc:
                log.warning("Could not update revocation progress UI: %s", exc)

    try:
        if payload["scope"] == "server":
            result = await _revoke_matching(
                guild, lambda _inv: True, f"Invitaciones revocadas por {interaction.user.name}", on_progress=on_progress)
        else:
            target_id = int(payload["userId"])
            result = await _revoke_matching(
                guild, lambda inv: bool(inv.inviter and inv.inviter.id == target_id),
                f"Invitaciones de {payload.get('userName') or target_id} revocadas por {interaction.user.name}",
                on_progress=on_progress,
            )
        await admin_actions.finish(bot.db, action.id, "completed",
                                   {"matched": result.matched, "revoked": result.revoked, "failed": len(result.failed)})
    except Exception as exc:
        await admin_actions.finish(bot.db, action.id, "failed", {"reason": str(exc)}, str(exc))
        log.exception("Invite revocation failed in %s", guild.id)
        await edit(content=f"La revocación se detuvo por un error: {str(exc)[:300]}", embed=None, view=None)
        return

    embed = discord.Embed(color=WARN if result.failed else OK, title="Revocación finalizada",
                          timestamp=discord.utils.utcnow())
    embed.add_field(name="Encontradas", value=str(result.matched), inline=True)
    embed.add_field(name="Revocadas", value=str(result.revoked), inline=True)
    embed.add_field(name="Errores", value=str(len(result.failed)), inline=True)
    embed.set_footer(text="El historial interno de invitadores e invitados se conservó.")
    if result.failed:
        embed.add_field(name="No se pudieron revocar", inline=False,
                        value="\n".join(f"• `{code}`: {reason}" for code, reason, _ in result.failed[:10])[:1024])
    await edit(embed=embed, view=None, allowed_mentions=discord.AllowedMentions.none())
