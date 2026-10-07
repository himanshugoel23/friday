import asyncio
from datetime import timedelta

import pytest

from friday.core.scale import (
    Job,
    JobPriority,
    JobStatus,
    LockTimeout,
    MemoryCache,
    MemoryIdempotencyStore,
    MemoryJobQueue,
    MemoryLock,
    MemoryRateLimiter,
    OutboxEntry,
    QueueOutbox,
)


async def test_job_queue_priority_due_and_dedupe(clock):
    q = MemoryJobQueue(clock)
    later = await q.enqueue(Job(kind="nudge", priority=JobPriority.PROACTIVE))
    live = await q.enqueue(Job(kind="answer", priority=JobPriority.LIVE))
    await q.enqueue(Job(kind="future", due_at=clock.now() + timedelta(hours=1)))
    dup = await q.enqueue(Job(kind="nudge", dedupe_key="n:1"))
    assert (await q.enqueue(Job(kind="nudge", dedupe_key="n:1"))).id == dup.id
    assert await q.depth() == 3
    claimed = await q.claim("w1", limit=2)
    assert [j.id for j in claimed][0] == live.id
    assert later.id not in [j.id for j in claimed] or len(claimed) == 2
    assert all(j.status == JobStatus.CLAIMED for j in claimed)
    assert await q.claim("w2", kinds=["future"]) == []  # not due yet


async def test_job_queue_retry_dead_letter_and_lease_expiry(clock):
    q = MemoryJobQueue(clock)
    job = await q.enqueue(Job(kind="call.place", max_attempts=2))
    [c1] = await q.claim("w1", lease_s=60)
    assert await q.claim("w2") == []  # held by w1
    clock.advance(61)
    [c2] = await q.claim("w2")  # w1 crashed: lease expired
    assert c2.id == c1.id == job.id
    again = await q.retry(job.id, error="boom", delay_s=10)
    assert again.status == JobStatus.QUEUED and again.attempts == 1
    clock.advance(10)
    await q.claim("w2")
    dead = await q.retry(job.id, error="boom")
    assert dead.status == JobStatus.DEAD
    other = await q.enqueue(Job(kind="x"))
    await q.claim("w")
    await q.ack(other.id)
    assert (await q.get(other.id)).status == JobStatus.DONE


async def test_outbox_enqueues_jobs(clock):
    q = MemoryJobQueue(clock)
    ob = QueueOutbox(q)
    await ob.add(OutboxEntry(kind="message.send", payload={"m": "1"}, dedupe_key="msg:1"))
    await ob.add(OutboxEntry(kind="message.send", payload={"m": "1"}, dedupe_key="msg:1"))
    assert await q.depth() == 1


async def test_memory_lock_serialises_and_cleans_up():
    lock = MemoryLock()
    order: list[str] = []

    async def turn(name: str) -> None:
        async with lock.hold("user:1"):
            order.append(name + "-in")
            await asyncio.sleep(0)
            order.append(name + "-out")

    await asyncio.gather(turn("a"), turn("b"))
    assert order in (["a-in", "a-out", "b-in", "b-out"], ["b-in", "b-out", "a-in", "a-out"])
    assert len(lock) == 0
    async with lock.hold("k"):
        with pytest.raises(LockTimeout):
            async with lock.hold("k", timeout_s=0.01):
                pass


async def test_cache_ttl_and_idempotency(clock):
    cache = MemoryCache(clock, max_entries=2)
    await cache.set("a", {"x": 1}, ttl_s=10)
    assert await cache.get("a") == {"x": 1}
    clock.advance(11)
    assert await cache.get("a") is None
    for k in "bcd":
        await cache.set(k, k)
    assert await cache.get("b") is None  # LRU evicted
    store = MemoryIdempotencyStore(clock)
    assert await store.first_seen("wa:wamid.1")
    assert not await store.first_seen("wa:wamid.1")


async def test_rate_limiter_bucket_and_slots(clock):
    rl = MemoryRateLimiter({"llm": 2.0}, {"sarvam": 1}, clock=clock)
    assert await rl.acquire("llm") and await rl.acquire("llm")
    assert not await rl.acquire("llm")  # bucket empty, no wait allowed
    assert await rl.acquire("llm", timeout_s=1.0)  # fake clock sleep refills
    assert await rl.acquire("unlimited")
    async with rl.slot("sarvam"):
        with pytest.raises(LockTimeout):
            async with rl.slot("sarvam", timeout_s=0.01):
                pass
