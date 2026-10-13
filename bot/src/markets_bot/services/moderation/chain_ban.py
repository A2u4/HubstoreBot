"""Chain ban: ban a whole invite tree connected to one account (with preview + confirmation).

Protected accounts (owner, staff, bots, higher roles) are never banned and act
as walls the walk does not pass through; otherwise a staff member sharing a
public invite would connect the target to most of the server.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import discord
from sqlalchemy import select

from markets_bot.core.utils import ERROR, INFO, OK, WARN
from markets_bot.db.models import Invite, ModAction
from markets_bot.services.moderation import admin_actions, invite_revocation
from markets_bot.services.moderation.state import PendingBan, pending_bans, remember_ban

if TYPE_CHECKING:
    from markets_bot.bot import MarketsBot

log = logging.getLogger(__name__)

MAX_CHAIN_ACCOUNTS = 250
MAX_PREVIEW = 30
MAX_PROTECTED_PREVIEW = 20
CONFIRMATION_TTL = timedelta(minutes=5)
CONFIRM_PREFIX = "mod_chain_ban_confirm_"
CANCEL_PREFIX = "mod_chain_ban_cancel_"


@dataclass(slots=True)
class Discovery:
    nodes: dict[str, int]  # account -> distance from target
    barriers: dict[str, int]  # protected accounts reached (never banned)
    exceeded_limit: bool


async def discover_network(
    relations: Iterable[tuple[str, str]], target_id: str, levels: int | None, max_accounts: int,
    is_barrier: Callable[[str], Awaitable[bool]],
) -> Discovery:
    """Breadth-first walk over invite relations in both directions."""
    neighbours: dict[str, set[str]] = {}
    for inviter, invited in relations:
        if inviter == invited:
            continue
        neighbours.setdefault(inviter, set()).add(invited)
        neighbours.setdefault(invited, set()).add(inviter)

    nodes = {target_id: 0}
    barriers: dict[str, int] = {}
    queue = deque([(target_id, 0)])
    max_depth = levels if levels is not None else float("inf")
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for nxt in sorted(neighbours.get(current, ())):
            if nxt in nodes or nxt in barriers:
                continue
            if await is_barrier(nxt):
                barriers[nxt] = depth + 1
                continue
            nodes[nxt] = depth + 1
            if len(nodes) > max_accounts:
                return Discovery(nodes, barriers, True)
            queue.append((nxt, depth + 1))
    return Discovery(nodes, barriers, False)


def _clean(name: str) -> str:
    return "".join(c for c in name if c not in "`*_~|")


async def _protection(
    bot: MarketsBot, guild: discord.Guild, moderator_id: int, user_id: int
) -> tuple[str | None, str]:
    """(reason the account is protected or None, display name)."""
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.HTTPException:
            member = None
    user: discord.abc.User | None = member
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.HTTPException:
            user = None
    name = _clean(user.name) if user else str(user_id)
    me = guild.me
    if user_id == moderator_id:
        return "Moderador que ejecutó el comando", name
    if user_id == guild.owner_id:
        return "Propietario del servidor", name
    if user_id == me.id:
        return "Bot actual", name
    if user is not None and user.bot:
        return "Cuenta de bot", name
    if member is not None:
        perms = member.guild_permissions
        if perms.administrator:
            return "Administrador", name
        if perms.ban_members or perms.moderate_members:
            return "Miembro del equipo de moderación", name
        if member.top_role >= me.top_role or member.id == guild.owner_id:
            return "Protegido por la jerarquía de roles", name
    return None, name


def _candidate_fields(candidates: list[dict[str, Any]]) -> list[tuple[str, str]]:
    preview = candidates[:MAX_PREVIEW]
    fields = []
    pages = (len(preview) + 9) // 10
    for i in range(0, len(preview), 10):
        part = "\n".join(f"• **{c['username']}** — `{c['id']}` · nivel {c['depth']}" for c in preview[i:i + 10])
        fields.append((f"Vista previa {i // 10 + 1}/{pages}" if len(preview) > 10 else "Vista previa", part or "Ninguna"))
    if len(candidates) > len(preview):
        fields.append(("Cuentas adicionales",
                       f"La vista previa muestra {len(preview)}. También se procesarán "
                       f"**{len(candidates) - len(preview)}** cuenta(s) adicional(es) después de confirmar."))
    return fields


def _protected_fields(accounts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    preview = accounts[:MAX_PROTECTED_PREVIEW]
    fields = []
    pages = (len(preview) + 9) // 10
    for i in range(0, len(preview), 10):
        part = "\n".join(f"• **{a['username']}** — `{a['id']}`: {a['protection']}" for a in preview[i:i + 10])
        fields.append((f"Protecciones {i // 10 + 1}/{pages}" if len(preview) > 10 else "Protecciones aplicadas",
                       part[:1024]))
    if len(accounts) > len(preview):
        fields.append(("Más cuentas protegidas",
                       f"Hay **{len(accounts) - len(preview)}** cuenta(s) protegida(s) adicional(es). "
                       "Ninguna será baneada."))
    return fields


async def prepare(
    bot: MarketsBot, interaction: discord.Interaction, target: discord.User, reason: str,
    delete_days: int, levels: int | None,
) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("Este modo solo funciona dentro de un servidor.", ephemeral=True)
        return
    if not interaction.permissions.administrator:
        await interaction.followup.send(
            "El baneo en cadena solo puede ser preparado y confirmado por un administrador.", ephemeral=True)
        return

    async with bot.db.session() as session:
        relations = (await session.execute(
            select(Invite.inviter_id, Invite.invited_id).where(Invite.guild_id == str(guild.id))
        )).all()

    protections: dict[str, tuple[str | None, str]] = {}

    async def lookup(user_id: str) -> tuple[str | None, str]:
        if user_id not in protections:
            protections[user_id] = await _protection(bot, guild, interaction.user.id, int(user_id))
        return protections[user_id]

    async def is_barrier(user_id: str) -> bool:
        return (await lookup(user_id))[0] is not None

    discovery = await discover_network(
        [(r[0], r[1]) for r in relations], str(target.id), levels, MAX_CHAIN_ACCOUNTS, is_barrier)
    if discovery.exceeded_limit:
        await interaction.followup.send(
            f"La cadena supera el límite de seguridad de **{MAX_CHAIN_ACCOUNTS} cuentas**.\n"
            "No se baneó a nadie. Usa `niveles` para limitar el alcance y revisa la vista previa.", ephemeral=True)
        return

    banned_ids = {str(entry.user.id) async for entry in guild.bans(limit=None)}
    candidates: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    revocation_ids: list[str] = []
    already_banned = 0
    for user_id, depth in sorted([*discovery.nodes.items(), *discovery.barriers.items()], key=lambda x: x[1]):
        reason_protected, name = await lookup(user_id)
        candidate = {"id": user_id, "username": name, "depth": depth}
        if reason_protected:
            protected.append({**candidate, "protection": reason_protected})
            continue
        revocation_ids.append(user_id)
        if user_id in banned_ids:
            already_banned += 1
            continue
        candidates.append(candidate)

    if not candidates:
        await interaction.followup.send(
            f"No hay cuentas elegibles para banear. Ya baneadas: **{already_banned}**; "
            f"protegidas: **{len(protected)}**.", ephemeral=True)
        return

    created = await admin_actions.create(
        bot.db, guild_id=str(guild.id), moderator_id=str(interaction.user.id), type_="chain-ban",
        payload={"targetId": str(target.id), "targetName": _clean(target.name), "reason": reason,
                 "deleteDays": delete_days, "levels": levels, "candidates": candidates,
                 "revocationIds": revocation_ids},
        total=len(candidates), expires_in=CONFIRMATION_TTL,
    )
    if not created.created:
        await interaction.followup.send(
            "Ya hay un baneo en cadena en curso en este servidor.\n"
            f"Progreso registrado: **{created.action.progress}/{created.action.total}**.\n"
            "Espera a que finalice antes de iniciar otro.", ephemeral=True)
        return

    embed = discord.Embed(
        color=ERROR, title="Confirmar baneo en cadena", timestamp=discord.utils.utcnow(),
        description=(
            f"Se inició desde **{_clean(target.name)}** (`{target.id}`).\n"
            "Incluye al usuario, su invitador directo, todos los invitados de ese invitador y cada generación "
            "posterior.\nEl recorrido sigue la dirección real de las invitaciones y no sube a antepasados ajenos."
            "\n\n**Revisa cuidadosamente la lista antes de confirmar.**"
        ),
    )
    embed.add_field(name="Cuentas que serán baneadas", value=str(len(candidates)), inline=True)
    embed.add_field(name="Alcance", value="Red completa" if levels is None else f"{levels} generación(es)", inline=True)
    embed.add_field(name="Ya baneadas", value=str(already_banned), inline=True)
    embed.add_field(name="Protegidas y excluidas", value=str(len(protected)), inline=True)
    embed.add_field(name="Mensajes a eliminar", value=f"{delete_days} día(s)", inline=True)
    embed.add_field(name="Motivo", value=reason[:1024], inline=False)
    for name, value in [*_candidate_fields(candidates), *(_protected_fields(protected) if protected else [])]:
        if len(embed.fields) < 25:
            embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text="La confirmación expira en 5 minutos. Los baneos pueden sincronizarse con los "
                          "servidores conectados.")
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=f"Confirmar {len(candidates)} baneo(s)", style=discord.ButtonStyle.danger,
                                    custom_id=f"{CONFIRM_PREFIX}{created.action.id}"))
    view.add_item(discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary,
                                    custom_id=f"{CANCEL_PREFIX}{created.action.id}"))
    await interaction.followup.send(embed=embed, view=view, ephemeral=True,
                                    allowed_mentions=discord.AllowedMentions.none())


async def handle_button(bot: MarketsBot, interaction: discord.Interaction) -> None:
    custom_id = str((interaction.data or {}).get("custom_id", ""))
    is_confirm = custom_id.startswith(CONFIRM_PREFIX)
    guild = interaction.guild
    if not interaction.permissions.administrator:
        await interaction.response.send_message("Ya no tienes permisos para confirmar este baneo.", ephemeral=True)
        return
    if guild is None:
        await interaction.response.send_message("Esta acción solo funciona dentro de un servidor.", ephemeral=True)
        return
    action_id = custom_id.removeprefix(CONFIRM_PREFIX if is_confirm else CANCEL_PREFIX)
    await interaction.response.defer()
    edit = interaction.edit_original_response

    if not is_confirm:
        outcome = await admin_actions.cancel(bot.db, action_id=action_id, type_="chain-ban",
                                             guild_id=str(guild.id), moderator_id=str(interaction.user.id))
        text = {"cancelled": "Baneo en cadena cancelado. No se baneó a nadie.",
                "replaced": "Esta confirmación fue reemplazada por una más reciente."}.get(
            outcome, "Esta confirmación ya no está pendiente.")
        await edit(content=text, embed=None, view=None)
        return

    claimed = await admin_actions.claim(bot.db, action_id=action_id, type_="chain-ban",
                                        guild_id=str(guild.id), moderator_id=str(interaction.user.id))
    if claimed.outcome != "claimed" or claimed.action is None:
        text = {
            **admin_actions.OUTCOME_TEXT,
            "expired": "Esta confirmación expiró. Ejecuta nuevamente `/mod banear`.",
            "running": "Este baneo en cadena ya está en curso.",
            "completed": "Este baneo en cadena ya finalizó.",
            "cancelled": "Este baneo en cadena fue cancelado.",
            "moderator-mismatch": "Solo el administrador que preparó la cadena puede confirmarla.",
        }.get(claimed.outcome, "Esta confirmación ya no se puede ejecutar.")
        await edit(content=text, embed=None, view=None)
        return

    action = claimed.action
    payload: dict[str, Any] = action.payload or {}
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not isinstance(payload.get("revocationIds"), list):
        await admin_actions.finish(bot.db, action.id, "failed", {"reason": "Payload inválido"},
                                   "Lista de candidatos inválida.")
        await edit(content="La confirmación guardada es inválida.", embed=None, view=None)
        return

    running = discord.Embed(color=INFO, title="Baneo en cadena en curso", timestamp=discord.utils.utcnow(),
                            description="Se están revalidando las protecciones y procesando las cuentas de forma segura.")
    running.add_field(name="Procesadas", value=f"0/{len(candidates)}", inline=True)
    running.add_field(name="Origen", value=str(payload.get("targetName")), inline=True)
    await edit(embed=running, view=None, allowed_mentions=discord.AllowedMentions.none())

    audit_reason = f"[Cadena de invitaciones] {payload.get('reason', '')}"[:500]
    revocation_ids = set(payload["revocationIds"])
    banned, skipped, failed, ready = [], [], [], []
    for candidate in candidates:
        protection, _ = await _protection(bot, guild, interaction.user.id, int(candidate["id"]))
        if protection:
            revocation_ids.discard(candidate["id"])
            skipped.append({**candidate, "reason": protection})
            continue
        try:
            await guild.fetch_ban(discord.Object(int(candidate["id"])))
            skipped.append({**candidate, "reason": "Ya estaba baneado"})
            continue
        except discord.NotFound:
            ready.append(candidate)

    try:
        revoked = await invite_revocation.revoke_for_users(
            guild, revocation_ids, f"Invitaciones revocadas por baneo en cadena de {payload.get('targetName')}")
    except discord.HTTPException as exc:
        revoked = invite_revocation.RevocationResult(failed=[("general", str(exc)[:180], None)])

    for candidate in ready:
        user_id = candidate["id"]
        try:
            remember_ban(user_id, PendingBan(str(guild.id), str(interaction.user.id), audit_reason, True))
            await guild.ban(discord.Object(int(user_id)), reason=audit_reason,
                            delete_message_seconds=int(payload.get("deleteDays", 7)) * 86400)
            async with bot.db.session() as session:
                session.add(ModAction(guild_id=str(guild.id), user_id=user_id,
                                      moderator_id=str(interaction.user.id), action="ban", reason=audit_reason))
            banned.append(candidate)
        except discord.HTTPException as exc:
            pending_bans.delete(user_id)
            failed.append({**candidate, "reason": str(exc)[:180]})
        await admin_actions.progress(bot.db, action.id, len(banned) + len(skipped) + len(failed), len(candidates))

    await admin_actions.finish(bot.db, action.id, "completed", {
        "banned": len(banned), "skipped": len(skipped), "failed": len(failed),
        "invitesRevoked": revoked.revoked, "inviteErrors": len(revoked.failed),
    })

    result = discord.Embed(color=WARN if failed or revoked.failed else OK, title="Resultado del baneo en cadena",
                           description=f"Cadena iniciada desde **{payload.get('targetName')}** (`{payload.get('targetId')}`).",
                           timestamp=discord.utils.utcnow())
    result.add_field(name="Baneados", value=str(len(banned)), inline=True)
    result.add_field(name="Omitidos", value=str(len(skipped)), inline=True)
    result.add_field(name="Errores", value=str(len(failed)), inline=True)
    result.add_field(name="Invitaciones revocadas", value=str(revoked.revoked), inline=True)
    result.add_field(name="Errores al revocar", value=str(len(revoked.failed)), inline=True)
    result.add_field(name="Motivo", value=str(payload.get("reason", ""))[:1024], inline=False)
    if failed:
        result.add_field(name="No se pudieron banear", inline=False, value="\n".join(
            f"• {a['username']} (`{a['id']}`): {a['reason']}" for a in failed[:10])[:1024])
    await edit(embed=result, view=None, allowed_mentions=discord.AllowedMentions.none())
