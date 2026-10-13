"""Economy persistence. Every balance change locks the account rows (``SELECT … FOR UPDATE``)
so concurrent commands (double-clicked /diario, simultaneous /pagar) can't create or lose money."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from markets_bot.core.db import Database
from markets_bot.core.errors import UserError
from markets_bot.core.utils import utcnow
from markets_bot.db.base import new_id
from markets_bot.db.models import EconomyAccount, EconomyInventory, EconomyItem

MAX_BALANCE = 2_000_000_000  # stays inside a Postgres INTEGER
_AMOUNT_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([km]?)$", re.IGNORECASE)


class EconomyError(UserError):
    """User-facing failure (insufficient funds, cooldown...)."""


def parse_amount(text: str, available: int) -> int:
    """Parse ``500``, ``2.5k``, ``1m``, ``todo``/``all`` or ``mitad``/``half`` against ``available``."""
    raw = text.strip().lower().replace(" ", "")
    if raw in {"todo", "all", "max"}:
        return available
    if raw in {"mitad", "half"}:
        return available // 2
    match = _AMOUNT_RE.match(raw.replace("_", ""))
    if not match:
        raise EconomyError("Cantidad inválida. Usa un número, `2.5k`, `1m`, `todo` o `mitad`.")
    value = float(match.group(1).replace(",", "."))
    value *= {"": 1, "k": 1_000, "m": 1_000_000}[match.group(2)]
    if value < 1:
        raise EconomyError("La cantidad debe ser mayor que 0.")
    return int(min(value, MAX_BALANCE))


def remaining(last: datetime | None, cooldown_seconds: int, now: datetime) -> int:
    if last is None:
        return 0
    return max(0, int((last + timedelta(seconds=cooldown_seconds) - now).total_seconds()))


class EconomyService:
    def __init__(self, db: Database) -> None:
        self.db = db

    @asynccontextmanager
    async def locked(self, guild_id: str, *user_ids: str, start_balance: int = 0
                     ) -> AsyncIterator[tuple[AsyncSession, dict[str, EconomyAccount]]]:
        """Open a transaction holding row locks on the given accounts (created if missing).

        Rows are locked in sorted order so two transfers between the same pair can't deadlock.
        """
        ids = sorted(set(user_ids))
        async with self.db.session() as session:
            await session.execute(insert(EconomyAccount).values([
                {"id": new_id(), "guild_id": guild_id, "user_id": uid, "wallet": start_balance} for uid in ids
            ]).on_conflict_do_nothing(index_elements=["guildId", "userId"]))
            rows = (await session.execute(
                select(EconomyAccount).where(EconomyAccount.guild_id == guild_id, EconomyAccount.user_id.in_(ids))
                .order_by(EconomyAccount.user_id).with_for_update())).scalars().all()
            yield session, {row.user_id: row for row in rows}

    async def get(self, guild_id: str, user_id: str) -> EconomyAccount | None:
        async with self.db.session() as session:
            return (await session.execute(select(EconomyAccount).where(
                EconomyAccount.guild_id == guild_id, EconomyAccount.user_id == user_id))).scalar_one_or_none()

    async def rank(self, guild_id: str, total: int) -> int:
        async with self.db.session() as session:
            above = await session.scalar(select(func.count()).select_from(EconomyAccount).where(
                EconomyAccount.guild_id == guild_id, EconomyAccount.wallet + EconomyAccount.bank > total))
        return int(above or 0) + 1

    async def leaderboard(self, guild_id: str, offset: int, limit: int) -> tuple[list[EconomyAccount], int]:
        net = EconomyAccount.wallet + EconomyAccount.bank
        async with self.db.session() as session:
            total = await session.scalar(select(func.count()).select_from(EconomyAccount).where(
                EconomyAccount.guild_id == guild_id, net > 0))
            rows = (await session.execute(select(EconomyAccount).where(EconomyAccount.guild_id == guild_id, net > 0)
                                          .order_by(net.desc()).offset(offset).limit(limit))).scalars().all()
        return list(rows), int(total or 0)

    # ── Items ────────────────────────────────────────────────────────────

    async def items(self, guild_id: str, *, only_active: bool = True) -> list[EconomyItem]:
        query = select(EconomyItem).where(EconomyItem.guild_id == guild_id)
        if only_active:
            query = query.where(EconomyItem.active.is_(True))
        async with self.db.session() as session:
            return list((await session.execute(query.order_by(EconomyItem.price, EconomyItem.name))).scalars())

    async def inventory(self, guild_id: str, user_id: str) -> list[EconomyInventory]:
        async with self.db.session() as session:
            return list((await session.execute(
                select(EconomyInventory).join(EconomyAccount, EconomyAccount.id == EconomyInventory.account_id)
                .where(EconomyAccount.guild_id == guild_id, EconomyAccount.user_id == user_id,
                       EconomyInventory.quantity > 0))).scalars().unique())

    async def buy(self, guild_id: str, user_id: str, item_id: str, quantity: int, start_balance: int
                  ) -> tuple[EconomyItem, int]:
        """Charge the wallet, decrement stock, add to inventory. Returns ``(item, new_wallet)``."""
        async with self.locked(guild_id, user_id, start_balance=start_balance) as (session, accounts):
            account = accounts[user_id]
            item = (await session.execute(select(EconomyItem).where(
                EconomyItem.id == item_id, EconomyItem.guild_id == guild_id, EconomyItem.active.is_(True))
                .with_for_update())).scalar_one_or_none()
            if item is None:
                raise EconomyError("Ese artículo ya no está disponible.")
            if item.stock is not None and item.stock < quantity:
                raise EconomyError(f"No hay suficiente stock (quedan {item.stock}).")
            cost = item.price * quantity
            if account.wallet < cost:
                raise EconomyError(f"Necesitas **{cost:,}** en la cartera y tienes **{account.wallet:,}**.")
            account.wallet -= cost
            if item.stock is not None:
                item.stock -= quantity
            await session.execute(insert(EconomyInventory).values(
                id=new_id(), account_id=account.id, item_id=item.id, quantity=quantity
            ).on_conflict_do_update(index_elements=["accountId", "itemId"],
                                    set_={"quantity": EconomyInventory.quantity + quantity}))
            return item, account.wallet

    @staticmethod
    def now() -> datetime:
        return utcnow()
