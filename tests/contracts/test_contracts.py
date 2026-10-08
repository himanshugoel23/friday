"""One behavioural contract per primitive, run against every implementation."""

from __future__ import annotations

import asyncio

import pytest

from friday.core.scale import Job, JobPriority, JobStatus, LockTimeout

# ------------------------------------------------------------------ JobQueue


async def test_queue_enqueue_claim_ack(queue):
    q, _ = queue
    j = await q.enqueue(Job(kind="task.step", payload={"task": "t1"}))
    assert (await q.get(j.id)).status == JobStatus.QUEUED
    assert await q.depth() == 1
    (got,) = await q.claim("w1", kinds=["task.step"])
    assert got.id == j.id and got.claimed_by == "w1" and got.payload == {"task": "t1"}
    assert await q.claim("w2") == []
    await q.ack(j.id)
    assert (await q.get(j.id)).status == JobStatus.DONE
    assert await q.depth() == 0


async def test_queue_claims_by_priority_then_due_time_and_filters_kind(queue):
    q, t = queue
    low = await q.enqueue(Job(kind="a", priority=JobPriority.BATCH))
    live = await q.enqueue(Job(kind="a", priority=JobPriority.LIVE))
    other = await q.enqueue(Job(kind="b"))
    later = await q.enqueue(Job(kind="a", priority=JobPriority.LIVE, due_at=None))
    got = await q.claim("w", kinds=["a"], limit=10)
    assert [g.kind for g in got] == ["a", "a", "a"] and got[-1].id == low.id
    assert {live.id, later.id} == {g.id for g in got[:2]}
    assert [g.id for g in await q.claim("w", kinds=["b"])] == [other.id]


async def test_queue_future_jobs_are_not_claimable_until_due(queue, clock):
    from datetime import timedelta

    q, t = queue
    j = await q.enqueue(Job(kind="a", due_at=clock.now() + timedelta(seconds=60)))
    assert await q.claim("w") == [] and await q.depth() == 0
    assert await q.depth(due_only=False) == 1
    await t.pass_(61)
    assert [g.id for g in await q.claim("w")] == [j.id]


async def test_queue_dedupe_key_returns_the_live_job(queue):
    q, _ = queue
    a = await q.enqueue(Job(kind="a", dedupe_key="k1"))
    b = await q.enqueue(Job(kind="a", dedupe_key="k1"))
    assert a.id == b.id and await q.depth() == 1


async def test_queue_expired_lease_is_reclaimed(queue):
    q, t = queue
    j = await q.enqueue(Job(kind="a"))
    (first,) = await q.claim("crashed", lease_s=30)
    assert await q.claim("other") == []
    await t.pass_(31)
    (again,) = await q.claim("other")
    assert again.id == j.id == first.id and again.claimed_by == "other"


async def test_queue_extend_lease_prevents_reclaim(queue):
    q, t = queue
    j = await q.enqueue(Job(kind="a"))
    await q.claim("w", lease_s=30)
    await t.pass_(20)
    await q.extend_lease(j.id, 60)
    await t.pass_(40)
    assert await q.claim("other") == []


async def test_queue_retry_backoff_then_dead_letter(queue):
    q, t = queue
    j = await q.enqueue(Job(kind="a", max_attempts=2))
    await q.claim("w")
    r1 = await q.retry(j.id, error="boom", delay_s=10)
    assert r1.status == JobStatus.QUEUED and r1.attempts == 1
    assert await q.claim("w") == []  # backing off
    await t.pass_(11)
    await q.claim("w")
    r2 = await q.retry(j.id, error="boom", delay_s=10)
    assert r2.status == JobStatus.DEAD and r2.last_error == "boom"
    await t.pass_(60)
    assert await q.claim("w") == []


async def test_queue_concurrent_claimers_never_share_a_job(queue):
    q, _ = queue
    ids = {(await q.enqueue(Job(kind="a"))).id for _ in range(30)}
    batches = await asyncio.gather(*[q.claim(f"w{i}", limit=5) for i in range(8)])
    claimed = [j.id for b in batches for j in b]
    assert len(claimed) == len(set(claimed))  # no duplicate delivery
    # (a claimer may legitimately come back empty-handed under contention; drain the rest)
    while rest := await q.claim("drain", limit=10):
        claimed += [j.id for j in rest]
    assert len(claimed) == len(set(claimed)) and set(claimed) == ids


# ------------------------------------------------------------------ IdempotencyStore


async def test_idempotency_first_seen_once(idempotency):
    store, _ = idempotency
    assert await store.first_seen("wa:1") is True
    assert await store.first_seen("wa:1") is False
    assert await store.first_seen("wa:2") is True


async def test_idempotency_key_expires(idempotency):
    store, t = idempotency
    assert await store.first_seen("k", ttl_s=1) is True
    assert await store.first_seen("k", ttl_s=1) is False
    await t.pass_(1.6)
    assert await store.first_seen("k", ttl_s=1) is True


async def test_idempotency_concurrent_duplicates_admit_exactly_one(idempotency):
    store, _ = idempotency
    results = await asyncio.gather(*[store.first_seen("same") for _ in range(20)])
    assert results.count(True) == 1


# ------------------------------------------------------------------ DistributedLock


async def test_lock_is_mutually_exclusive(lock):
    inside = 0
    peak = 0

    async def worker():
        nonlocal inside, peak
        async with lock.hold("user:1", timeout_s=5):
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.01)
            inside -= 1

    await asyncio.gather(*[worker() for _ in range(6)])
    assert peak == 1


async def test_lock_times_out_while_held_and_keys_are_independent(lock):
    async with lock.hold("a", timeout_s=1):
        async with lock.hold("b", timeout_s=1):  # a different key is free
            pass
        with pytest.raises(LockTimeout):
            async with lock.hold("a", timeout_s=0.1):
                pass
    async with lock.hold("a", timeout_s=1):  # released afterwards
        pass


async def test_lock_is_released_when_the_body_raises(lock):
    with pytest.raises(RuntimeError):
        async with lock.hold("k", timeout_s=1):
            raise RuntimeError("x")
    async with lock.hold("k", timeout_s=0.5):
        pass


# ------------------------------------------------------------------ Cache


async def test_cache_roundtrip_delete_and_json_values(cache):
    c, _ = cache
    assert await c.get("missing") is None
    value = {"a": [1, 2, {"b": "c"}], "n": None}
    await c.set("k", value)
    assert await c.get("k") == value
    await c.delete("k")
    assert await c.get("k") is None


async def test_cache_ttl_expires(cache):
    c, t = cache
    await c.set("k", "v", ttl_s=1)
    assert await c.get("k") == "v"
    await t.pass_(1.6)
    assert await c.get("k") is None


# ------------------------------------------------------------------ RateLimiter


async def test_rate_limiter_token_bucket(limiter_factory):
    make, t = limiter_factory
    rl = make({"llm": 2.0})  # 2 tokens/s, 1 s burst -> capacity 2
    assert await rl.acquire("llm") is True
    assert await rl.acquire("llm") is True
    assert await rl.acquire("llm") is False  # empty, no waiting allowed
    await t.pass_(0.6)
    assert await rl.acquire("llm") is True  # refilled
    assert await rl.acquire("unlimited-key") is True  # no rate configured -> not limited


async def test_rate_limiter_can_wait_for_a_token(limiter_factory):
    make, _ = limiter_factory
    rl = make({"k": 20.0})
    for _ in range(20):
        assert await rl.acquire("k")
    assert await rl.acquire("k", timeout_s=1.0) is True  # waits ~50 ms for the next token


async def test_rate_limiter_concurrency_slots(limiter_factory):
    make, _ = limiter_factory
    rl = make(None, {"sarvam": 2})
    peak = inside = 0

    async def user():
        nonlocal inside, peak
        async with rl.slot("sarvam", timeout_s=5):
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.02)
            inside -= 1

    await asyncio.gather(*[user() for _ in range(8)])
    assert peak == 2
    async with rl.slot("sarvam"), rl.slot("sarvam"):
        with pytest.raises(LockTimeout):
            async with rl.slot("sarvam", timeout_s=0.1):
                pass
