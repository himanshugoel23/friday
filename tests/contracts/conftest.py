"""S-12: contract kit for the scale-out primitives. Every implementation of a primitive must
pass the same tests. Memory and SQL(SQLite) run always; Postgres needs FRIDAY_TEST_PG_URL and
Redis needs FRIDAY_TEST_REDIS_URL (both skipped otherwise)."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.scale import (
    MemoryCache,
    MemoryIdempotencyStore,
    MemoryJobQueue,
    MemoryLock,
    MemoryRateLimiter,
)
from friday.db import Database
from friday.db.idempotency import SqlIdempotencyStore
from friday.db.locks import PgLock
from friday.db.queue import SqlJobQueue

PG_URL = os.environ.get("FRIDAY_TEST_PG_URL")
REDIS_URL = os.environ.get("FRIDAY_TEST_REDIS_URL")


@dataclass
class Time:
    """Moves time for an implementation: instantly on a FakeClock, really for Redis."""

    clock: FakeClock | None

    async def pass_(self, seconds: float) -> None:
        if self.clock is not None:
            self.clock.advance(seconds)
        else:
            await asyncio.sleep(seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 1, 5, 10, 0, tzinfo=IST))


async def _db(kind: str):
    if kind == "postgres" and not PG_URL:
        pytest.skip("FRIDAY_TEST_PG_URL not set")
    db = Database(PG_URL if kind == "postgres" else "sqlite+aiosqlite:///:memory:")
    if kind == "postgres":
        await db.drop_all()
    await db.create_all()
    return db


async def _redis():
    if not REDIS_URL:
        pytest.skip("FRIDAY_TEST_REDIS_URL not set")
    import redis.asyncio as aioredis

    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    await client.flushdb()
    return client


@pytest.fixture(params=["memory", "sql", pytest.param("postgres", marks=pytest.mark.postgres)])
async def queue(request, clock):
    if request.param == "memory":
        yield MemoryJobQueue(clock), Time(clock)
        return
    db = await _db(request.param)
    try:
        yield SqlJobQueue(db, clock), Time(clock)
    finally:
        if request.param == "postgres":
            await db.drop_all()
        await db.dispose()


@pytest.fixture(params=["memory", "sql", pytest.param("postgres", marks=pytest.mark.postgres)])
async def idempotency(request, clock):
    if request.param == "memory":
        yield MemoryIdempotencyStore(clock), Time(clock)
        return
    db = await _db(request.param)
    try:
        yield SqlIdempotencyStore(db, clock), Time(clock)
    finally:
        if request.param == "postgres":
            await db.drop_all()
        await db.dispose()


@pytest.fixture(params=["memory", "sql", pytest.param("redis", marks=pytest.mark.redis)])
async def lock(request, clock):
    if request.param == "memory":
        yield MemoryLock()
    elif request.param == "sql":
        db = await _db("sqlite")
        try:
            yield PgLock(db)
        finally:
            await db.dispose()
    else:
        from friday.db.redis_backends import RedisLock

        client = await _redis()
        try:
            yield RedisLock(client, ttl_ms=5_000, poll_s=0.01)
        finally:
            await client.aclose()


@pytest.fixture(params=["memory", pytest.param("redis", marks=pytest.mark.redis)])
async def cache(request, clock):
    if request.param == "memory":
        yield MemoryCache(clock), Time(clock)
        return
    from friday.db.redis_backends import RedisCache

    client = await _redis()
    try:
        yield RedisCache(client), Time(None)
    finally:
        await client.aclose()


@pytest.fixture(params=["memory", pytest.param("redis", marks=pytest.mark.redis)])
async def limiter_factory(request, clock):
    """Returns ``make(rates, concurrency)`` and a Time helper."""
    if request.param == "memory":
        yield (lambda rates=None, conc=None: MemoryRateLimiter(rates, conc, clock=clock)), Time(
            clock
        )
        return
    from friday.db.redis_backends import RedisRateLimiter

    client = await _redis()
    try:
        yield (lambda rates=None, conc=None: RedisRateLimiter(client, rates, conc)), Time(None)
    finally:
        await client.aclose()
