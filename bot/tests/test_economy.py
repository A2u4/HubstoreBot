import asyncio

import pytest
from sqlalchemy import func, select

from markets_bot.core.db import Database
from markets_bot.db.models import EconomyAccount, EconomyItem
from markets_bot.services.economy import EconomyError, EconomyService, parse_amount

from .conftest import requires_db


def test_parse_amount() -> None:
    assert parse_amount("500", 1000) == 500
    assert parse_amount("2.5k", 0) == 2500
    assert parse_amount("1M", 0) == 1_000_000
    assert parse_amount("todo", 777) == 777
    assert parse_amount("mitad", 777) == 388
    for bad in ("abc", "-5", "0", ""):
        with pytest.raises(EconomyError):
            parse_amount(bad, 100)


async def _transfer(eco: EconomyService, gid: str, src: str, dst: str, amount: int) -> bool:
    try:
        async with eco.locked(gid, src, dst) as (_, accounts):
            if accounts[src].wallet < amount:
                raise EconomyError("insufficient")
            accounts[src].wallet -= amount
            accounts[dst].wallet += amount
        return True
    except EconomyError:
        return False


@requires_db
async def test_concurrent_transfers_conserve_money(db: Database, guild_id: str) -> None:
    eco = EconomyService(db)
    users = ["1", "2", "3"]
    async with eco.locked(guild_id, *users, start_balance=1000):
        pass
    moves = [(users[i % 3], users[(i + 1) % 3], 70 + i) for i in range(60)]
    await asyncio.gather(*(_transfer(eco, guild_id, s, d, a) for s, d, a in moves))
    async with db.session() as session:
        total = await session.scalar(select(func.sum(EconomyAccount.wallet)).where(EconomyAccount.guild_id == guild_id))
        lowest = await session.scalar(select(func.min(EconomyAccount.wallet)).where(EconomyAccount.guild_id == guild_id))
    assert total == 3000
    assert lowest >= 0


@requires_db
async def test_buy_respects_stock_under_concurrency(db: Database, guild_id: str) -> None:
    eco = EconomyService(db)
    async with db.session() as session:
        item = EconomyItem(guild_id=guild_id, name="Rare", price=10, stock=3)
        session.add(item)
    buyers = [str(i) for i in range(10)]

    async def attempt(uid: str) -> bool:
        try:
            await eco.buy(guild_id, uid, item.id, 1, start_balance=100)
            return True
        except EconomyError:
            return False

    results = await asyncio.gather(*(attempt(uid) for uid in buyers))
    assert sum(results) == 3
    async with db.session() as session:
        assert (await session.get(EconomyItem, item.id)).stock == 0  # type: ignore[union-attr]
    inventory = await eco.inventory(guild_id, next(uid for uid, ok in zip(buyers, results, strict=True) if ok))
    assert inventory[0].item.name == "Rare"
