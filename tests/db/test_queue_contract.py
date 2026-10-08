"""JobQueue / IdempotencyStore / DistributedLock contract, run against the core memory
implementations AND the SQL ones (SQLite always, Postgres when FRIDAY_TEST_PG_URL is set)."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest

from friday.core.clock import FakeClock
from friday.core.scale import (
    Job,
    JobStatus,
    LockTimeout,
    MemoryIdempotencyStore,
    MemoryJobQueue,
    MemoryLock,
)
from friday.db import Database
from friday.db.idempotency import SqlIdempotencyStore
from friday.db.locks import PgLock
from friday.db.queue import SqlJobQueue

PG_URL = os.environ.get("FRIDAY_TEST_PG_URL")


@pytest.fixture(params=["memory", "sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
async def impl(request, clock: FakeClock):
    kind = request.param
    if kind == "memory":
        yield MemoryJobQueue(clock), MemoryIdempotencyStore(clock), MemoryLock()
        return
    if kind == "postgres" and not PG_URL:
        pytest.skip("FRIDAY_TEST_PG_URL not set")
    db = Database(PG_URL if kind == "postgres" else "sqlite+aiosqlite:///:memory:")
    if kind == "postgres":
        await db.drop_all()
    await db.create_all()
    try:
        yield SqlJobQueue(db, clock), SqlIdempotencyStore(db, clock), PgLock(db)
    finally:
        if kind == "postgres":
            await db.drop_all()
        await db.dispose()


async def test_enqueue_claim_ack(impl, clock):
    q, _, _ = impl
    j = await q.enqueue(Job(kind="task.step", payload={"task": "t1"}))
    assert (await q.get(j.id)).status == JobStatus.QUEUED
    assert await q.depth() == 1
    got = await q.claim("w1", kinds=["task.step"])
    assert [g.id for g in got] == [j.id] and got[0].claimed_by == "w1"
    assert await q.claim("w2") == []  # not claimable twice
    await q.ack(j.id)
    assert (await q.get(j.id)).status == JobStatus.DONE


async def test_priority_due_and_kind_filter(impl, clock):
    q, _, _ = impl
    await q.enqueue(Job(kind="nudge.send", priority=20))
    await q.enqueue(Job(kind="call.place", priority=0))
    await q.enqueue(Job(kind="task.step", due_at=clock.now() + timedelta(minutes=5)))
    first = await q.claim("w", limit=5)
    assert [j.kind for j in first] == ["call.place", "nudge.send"]  # future job not due
    clock.advance(minutes=6)
    assert [j.kind for j in await q.claim("w", kinds=["task.step"])] == ["task.step"]


async def test_dedupe_key_is_idempotent(impl):
    q, _, _ = impl
    a = await q.enqueue(Job(kind="message.send", dedupe_key="msg:1"))
    b = await q.enqueue(Job(kind="message.send", dedupe_key="msg:1"))
    assert a.id == b.id and await q.depth() == 1
    (c,) = await q.claim("w")
    await q.ack(c.id)
    d = await q.enqueue(Job(kind="message.send", dedupe_key="msg:1"))
    assert d.id != a.id  # finished jobs don't block a new one


async def test_lease_expiry_reclaims_crashed_worker(impl, clock):
    q, _, _ = impl
    j = await q.enqueue(Job(kind="call.place"))
    assert await q.claim("dead-worker", lease_s=30)
    assert await q.claim("w2") == []
    clock.advance(31)
    (re,) = await q.claim("w2")
    assert re.id == j.id and re.claimed_by == "w2"
    await q.extend_lease(j.id, 600)
    clock.advance(300)
    assert await q.claim("w3") == []


async def test_retry_backoff_then_dead_letter(impl, clock):
    q, _, _ = impl
    j = await q.enqueue(Job(kind="task.step", max_attempts=2))
    await q.claim("w")
    r = await q.retry(j.id, error="boom", delay_s=60)
    assert r.status == JobStatus.QUEUED and r.attempts == 1
    assert await q.claim("w") == []
    clock.advance(61)
    await q.claim("w")
    dead = await q.retry(j.id, error="boom again")
    assert dead.status == JobStatus.DEAD
    assert await q.claim("w") == []


async def test_two_claimers_never_get_the_same_job(impl):
    q, _, _ = impl
    ids = [(await q.enqueue(Job(kind="call.place", dedupe_key=f"c{i}"))).id for i in range(20)]
    batches = await asyncio.gather(*(q.claim(f"w{i}", limit=5) for i in range(8)))
    claimed = [j.id for b in batches for j in b]
    assert len(claimed) == len(set(claimed))  # never the same job twice
    while len(claimed) < 20:  # losers of a race simply claim the next batch
        more = [j.id for j in await q.claim("drain", limit=5)]
        assert more and not set(more) & set(claimed)
        claimed += more
    assert set(claimed) == set(ids)


async def test_idempotency_first_seen_and_expiry(impl, clock):
    _, idem, _ = impl
    assert await idem.first_seen("wa:1", ttl_s=60)
    assert not await idem.first_seen("wa:1", ttl_s=60)
    assert await idem.first_seen("wa:2", ttl_s=60)
    clock.advance(61)
    assert await idem.first_seen("wa:1", ttl_s=60)


async def test_lock_is_exclusive_and_times_out(impl):
    _, _, lock = impl
    order: list[str] = []

    async def worker(name: str) -> None:
        async with lock.hold("user:1", timeout_s=5):
            order.append(f"in:{name}")
            await asyncio.sleep(0.05)
            order.append(f"out:{name}")

    await asyncio.gather(worker("a"), worker("b"))
    assert order[0].startswith("in") and order[1].startswith("out")  # never interleaved
    assert order[2].startswith("in") and order[3].startswith("out")
    async with lock.hold("k", timeout_s=1):
        with pytest.raises(LockTimeout):
            async with lock.hold("k", timeout_s=0.1):
                pass
    async with lock.hold("k", timeout_s=1):
        pass  # released


async def test_enqueue_inside_callers_transaction_is_atomic(clock):
    """Transactional outbox: a rolled-back state change leaves no job behind."""
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.create_all()
    q = SqlJobQueue(db, clock)
    with pytest.raises(RuntimeError):
        async with db.session() as s:
            await q.enqueue(Job(kind="message.send", dedupe_key="m1"), session=s)
            raise RuntimeError("state change failed")
    assert await q.depth() == 0
    async with db.session() as s:
        await q.enqueue(Job(kind="message.send", dedupe_key="m1"), session=s)
    assert await q.depth() == 1
    await db.dispose()


async def test_dead_letter_hook_and_count(clock):
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.create_all()
    seen = []
    q = SqlJobQueue(db, clock, on_dead_letter=seen.append)
    j = await q.enqueue(Job(kind="call.place"))
    await q.dead_letter(j.id, error="provider down")
    assert [x.id for x in seen] == [j.id] and await q.dead_count() == 1
    await db.dispose()
