"""Async engine + session factory.

    db = Database(settings.database_url)
    await db.create_all()            # dev/tests; Postgres prod will use migrations later
    async with db.session() as s:    # commits on success, rolls back on error
        s.add(UserRow(...))

Owner: EM scaffold -> Backend Engineer after hand-off.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from friday.db.base import Base


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        kwargs: dict = {"echo": echo}
        is_sqlite = url.startswith("sqlite")
        if is_sqlite and (":memory:" in url or url.rstrip("/").endswith("sqlite+aiosqlite:")):
            # one shared connection so every session sees the same in-memory DB
            kwargs |= {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        elif is_sqlite:
            _ensure_sqlite_dir(url)
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        if is_sqlite:
            event.listen(self.engine.sync_engine, "connect", _sqlite_pragmas)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        import friday.db.tables  # noqa: F401  (register tables)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as s:
            try:
                yield s
                await s.commit()
            except BaseException:
                await s.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _ensure_sqlite_dir(url: str) -> None:
    path = url.split(":///", 1)[-1]
    if path and path != ":memory:":
        Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
