"""Durable confirmation records for destructive admin flows (chain ban, invite revocation).

Confirmation buttons can be clicked after a restart, so state lives in the
``pending_admin_actions`` table rather than in memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import or_, select, update

from markets_bot.core.db import Database
from markets_bot.core.utils import utcnow
from markets_bot.db.models import PendingAdminAction

RUNNING_STALE_AFTER = timedelta(hours=2)

ActionType = Literal["invite-revocation", "chain-ban"]


@dataclass(slots=True)
class Created:
    action: PendingAdminAction
    created: bool


@dataclass(slots=True)
class Claim:
    action: PendingAdminAction | None
    outcome: str  # claimed | missing | expired | guild-mismatch | moderator-mismatch | <status>


async def create(
    db: Database, *, guild_id: str, moderator_id: str, type_: ActionType,
    payload: dict[str, Any], total: int, expires_in: timedelta,
) -> Created:
    now = utcnow()
    async with db.session() as session:
        await session.execute(
            update(PendingAdminAction)
            .where(or_(
                (PendingAdminAction.status == "pending") & (PendingAdminAction.expires_at <= now),
                (PendingAdminAction.status == "running") & (PendingAdminAction.updated_at <= now - RUNNING_STALE_AFTER),
            ))
            .values(status="expired", consumed_at=now, error="La acción expiró antes de finalizar.")
        )
        running = (await session.execute(
            select(PendingAdminAction).where(
                PendingAdminAction.guild_id == guild_id, PendingAdminAction.type == type_,
                PendingAdminAction.status == "running",
            ).order_by(PendingAdminAction.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if running:
            return Created(running, False)
        # A new preview supersedes older unconfirmed previews from the same admin.
        await session.execute(
            update(PendingAdminAction)
            .where(
                PendingAdminAction.guild_id == guild_id, PendingAdminAction.moderator_id == moderator_id,
                PendingAdminAction.type == type_, PendingAdminAction.status == "pending",
            )
            .values(status="replaced", consumed_at=now)
        )
        action = PendingAdminAction(
            guild_id=guild_id, moderator_id=moderator_id, type=type_, payload=payload,
            total=total, expires_at=now + expires_in,
        )
        session.add(action)
        await session.flush()
        return Created(action, True)


async def claim(db: Database, *, action_id: str, type_: ActionType, guild_id: str, moderator_id: str) -> Claim:
    now = utcnow()
    async with db.session() as session:
        action = (await session.execute(
            select(PendingAdminAction).where(PendingAdminAction.id == action_id, PendingAdminAction.type == type_)
        )).scalar_one_or_none()
        if action is None:
            return Claim(None, "missing")
        if action.guild_id != guild_id:
            return Claim(action, "guild-mismatch")
        if action.moderator_id != moderator_id:
            return Claim(action, "moderator-mismatch")
        if action.expires_at <= now or action.status == "expired":
            await session.execute(
                update(PendingAdminAction)
                .where(PendingAdminAction.id == action.id, PendingAdminAction.status == "pending")
                .values(status="expired", consumed_at=now)
            )
            return Claim(action, "expired")
        if action.status != "pending":
            return Claim(action, action.status)
        result = await session.execute(
            update(PendingAdminAction)
            .where(PendingAdminAction.id == action.id, PendingAdminAction.status == "pending")
            .values(status="running", consumed_at=now, progress=0, error=None)
        )
        await session.refresh(action)
        return Claim(action, "claimed" if result.rowcount == 1 else action.status)


async def cancel(db: Database, *, action_id: str, type_: ActionType, guild_id: str, moderator_id: str) -> str:
    async with db.session() as session:
        action = (await session.execute(
            select(PendingAdminAction).where(PendingAdminAction.id == action_id, PendingAdminAction.type == type_)
        )).scalar_one_or_none()
        if action is None:
            return "missing"
        if action.guild_id != guild_id:
            return "guild-mismatch"
        if action.moderator_id != moderator_id:
            return "moderator-mismatch"
        if action.status != "pending":
            return action.status
        result = await session.execute(
            update(PendingAdminAction)
            .where(PendingAdminAction.id == action.id, PendingAdminAction.status == "pending")
            .values(status="cancelled", consumed_at=utcnow())
        )
        return "cancelled" if result.rowcount == 1 else "changed"


async def progress(db: Database, action_id: str, done: int, total: int) -> None:
    async with db.session() as session:
        await session.execute(
            update(PendingAdminAction)
            .where(PendingAdminAction.id == action_id, PendingAdminAction.status == "running")
            .values(progress=done, total=total)
        )


async def finish(db: Database, action_id: str, status: Literal["completed", "failed"],
                 result: dict[str, Any], error: str | None = None) -> None:
    async with db.session() as session:
        await session.execute(
            update(PendingAdminAction).where(PendingAdminAction.id == action_id)
            .values(status=status, result=result, error=error[:1000] if error else None, consumed_at=utcnow())
        )


OUTCOME_TEXT = {
    "missing": "Esta confirmación no existe.",
    "replaced": "Esta confirmación fue reemplazada por una más reciente.",
    "guild-mismatch": "El servidor de esta confirmación no coincide.",
}
