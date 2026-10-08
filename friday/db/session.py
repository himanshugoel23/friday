"""Async engine + session factory.

    db = Database(settings.database_url)
    await db.create_all()            # dev/tests; Postgres prod will use migrations later
    async with db.session() as s:    # commits on success, rolls back on error
        s.add(UserRow(...))

Owner: EM scaffold -> Backend Engineer after hand-off.
"""

from __future__ import annotations

import uuid
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


def async_url(url: str) -> str:
    """Accept plain ``postgresql://`` / ``postgres://`` and select the asyncpg driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


class Database:
    """Engine + session factory.

    Postgres (S-5): pooled (``db_pool_size`` / ``db_max_overflow`` / ``db_pool_timeout_s``
    from Settings unless passed), ``pool_pre_ping`` for failovers, and **PgBouncer
    transaction-pooling safe**: no prepared-statement cache and unique statement names,
    and nothing in this codebase relies on session state (advisory locks are the
    transaction-scoped ``pg_advisory_xact_lock`` variants)."""

    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        pool_size: int | None = None,
        max_overflow: int | None = None,
        pool_timeout_s: float | None = None,
    ) -> None:
        url = async_url(url)
        self.url = url
        kwargs: dict = {"echo": echo}
        is_sqlite = url.startswith("sqlite")
        if is_sqlite and (":memory:" in url or url.rstrip("/").endswith("sqlite+aiosqlite:")):
            # one shared connection so every session sees the same in-memory DB
            kwargs |= {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        elif is_sqlite:
            _ensure_sqlite_dir(url)
        elif url.startswith("postgresql"):
            from friday.core.config import Settings

            cfg = Settings()
            kwargs |= {
                "pool_size": cfg.db_pool_size if pool_size is None else pool_size,
                "max_overflow": cfg.db_max_overflow if max_overflow is None else max_overflow,
                "pool_timeout": cfg.db_pool_timeout_s if pool_timeout_s is None else pool_timeout_s,
                "pool_pre_ping": True,
                "connect_args": {
                    "statement_cache_size": 0,
                    "prepared_statement_cache_size": 0,
                    "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4().hex}__",
                },
            }
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
