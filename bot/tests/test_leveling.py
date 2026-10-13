import asyncio

from markets_bot.core.db import Database
from markets_bot.services.leveling import LevelService, Progress, level_from_xp, total_xp_for, xp_to_next

from .conftest import requires_db


def test_curve_matches_mee6() -> None:
    assert [xp_to_next(n) for n in range(4)] == [100, 155, 220, 295]
    assert total_xp_for(1) == 100 and total_xp_for(2) == 255
    for level in range(0, 60):
        assert level_from_xp(total_xp_for(level)) == level
        if level:
            assert level_from_xp(total_xp_for(level) - 1) == level - 1
    progress = Progress.of(300)
    assert (progress.level, progress.current, progress.needed) == (2, 45, 220)


@requires_db
async def test_level_up_reported_once(db: Database, guild_id: str) -> None:
    levels = LevelService(db)
    results = await asyncio.gather(*(levels.add_xp(guild_id, "42", 10) for _ in range(30)))
    ups = [r for r in results if r is not None]
    row = await levels.get(guild_id, "42")
    assert row is not None and row.xp == 300 and row.level == 2
    assert sorted(new for _, new, _ in ups) == sorted({new for _, new, _ in ups})  # no level announced twice
    assert await levels.set_xp(guild_id, "42", 0) == 0
