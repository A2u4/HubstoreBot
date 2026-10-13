"""Shared fixtures. DB tests run only when TEST_DATABASE_URL points at a migrated database."""

from __future__ import annotations

import os
import random
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete

from markets_bot.core.db import Database
from markets_bot.db.models import GuildConfig

DB_URL = os.environ.get("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    database = Database(DB_URL)  # type: ignore[arg-type]
    yield database
    await database.close()


@pytest.fixture
async def guild_id(db: Database) -> AsyncIterator[str]:
    """A throwaway guild row (child rows cascade on delete)."""
    gid = str(random.randint(10**17, 10**18))
    async with db.session() as session:
        session.add(GuildConfig(id=gid))
    yield gid
    async with db.session() as session:
        await session.execute(delete(GuildConfig).where(GuildConfig.id == gid))
