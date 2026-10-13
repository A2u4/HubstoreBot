"""Async database access (SQLAlchemy 2 + asyncpg)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Database:
    def __init__(self, url: str, *, pool_size: int = 5, max_overflow: int = 5) -> None:
        self.engine = create_async_engine(
            url, pool_size=pool_size, max_overflow=max_overflow, pool_pre_ping=True, pool_recycle=1800
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self, *, isolation_level: str | None = None) -> AsyncIterator[AsyncSession]:
        """A unit of work: commits on success, rolls back on error."""
        async with self._sessions() as session:
            if isolation_level:
                await session.connection(execution_options={"isolation_level": isolation_level})
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def close(self) -> None:
        await self.engine.dispose()
