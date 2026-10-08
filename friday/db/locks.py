"""Distributed locks on Postgres advisory locks (S-3).

``async with lock.hold(f"sender:{phone}")`` takes ``pg_advisory_xact_lock(hashtext(key))``
inside a transaction on its own connection: the lock is released when the block ends (or
the connection dies), so a crashed replica can never wedge a user. ``timeout_s`` is
enforced with ``pg_try_advisory_xact_lock`` polling (no server-side blocking, PgBouncer
transaction-pooling safe). Off Postgres (dev/tests on SQLite) it degrades to the
in-process ``MemoryLock``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text

from friday.core.scale import LockTimeout, MemoryLock
from friday.db.session import Database

if TYPE_CHECKING:
    from friday.core.container import Container

TRY_LOCK = text("SELECT pg_try_advisory_xact_lock(hashtext(:k))")


class PgLock:
    def __init__(self, db: Database, *, poll_s: float = 0.05) -> None:
        self.db = db
        self.poll_s = poll_s
        self._fallback = MemoryLock()

    @asynccontextmanager
    async def hold(self, key: str, *, timeout_s: float = 10.0) -> AsyncIterator[None]:
        if self.db.engine.dialect.name != "postgresql":
            async with self._fallback.hold(key, timeout_s=timeout_s):
                yield
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        async with self.db.engine.connect() as conn, conn.begin():
            while True:
                got = (await conn.execute(TRY_LOCK, {"k": key})).scalar_one()
                if got:
                    break
                if loop.time() >= deadline:
                    raise LockTimeout(key)
                await asyncio.sleep(self.poll_s)
            yield


def build_pg_lock(c: Container) -> PgLock:
    return PgLock(c.db)
