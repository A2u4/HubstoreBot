"""Every ORM column must exist in the Prisma-managed schema (and vice versa).

Runs only when TEST_DATABASE_URL points at a database migrated with
``prisma migrate deploy``.
"""

import os

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from markets_bot.db.models import Base

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


async def test_models_match_database_columns() -> None:
    engine = create_async_engine(DB_URL)  # type: ignore[arg-type]
    try:
        async with engine.connect() as conn:
            db_columns = await conn.run_sync(
                lambda sync: {
                    table: {c["name"] for c in inspect(sync).get_columns(table)}
                    for table in inspect(sync).get_table_names()
                }
            )
    finally:
        await engine.dispose()

    problems = []
    for table in Base.metadata.sorted_tables:
        model_cols = {c.name for c in table.columns}
        actual = db_columns.get(table.name)
        if actual is None:
            problems.append(f"missing table {table.name}")
            continue
        if extra := model_cols - actual:
            problems.append(f"{table.name}: model has unknown columns {sorted(extra)}")
        if missing := actual - model_cols:
            problems.append(f"{table.name}: model lacks columns {sorted(missing)}")
    assert not problems, "\n".join(problems)
