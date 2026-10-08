"""Webhook de-duplication in the database (S-1/S-2): one row per delivery key."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from friday.core.clock import Clock, SystemClock
from friday.db.session import Database
from friday.db.tables import IdempotencyKeyRow

if TYPE_CHECKING:
    from friday.core.container import Container


class SqlIdempotencyStore:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db = db
        self.clock: Clock = clock or SystemClock()

    async def first_seen(self, key: str, *, ttl_s: int = 72 * 3600) -> bool:
        now = self.clock.now()
        try:
            async with self.db.session() as s:
                await s.execute(
                    delete(IdempotencyKeyRow).where(
                        IdempotencyKeyRow.key == key, IdempotencyKeyRow.expires_at <= now
                    )
                )
                s.add(IdempotencyKeyRow(key=key, expires_at=now + timedelta(seconds=ttl_s)))
        except IntegrityError:
            return False
        return True

    async def purge_expired(self) -> int:
        async with self.db.session() as s:
            res = await s.execute(
                delete(IdempotencyKeyRow).where(IdempotencyKeyRow.expires_at <= self.clock.now())
            )
            return int(res.rowcount or 0)


def build_pg_idempotency(c: Container) -> SqlIdempotencyStore:
    return SqlIdempotencyStore(c.db, c.clock)
