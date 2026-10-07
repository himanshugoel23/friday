"""Scale-out contracts (founder: "built for scale") + in-memory implementations.

The in-process ``EventBus`` stays for NON-critical notifications. Anything that must
not be lost, must run exactly once, or may run on another replica goes through these:

* ``JobQueue``        durable jobs: priority, due_at, dedupe key; claim/ack/retry/dead-letter.
                      Postgres impl (``FOR UPDATE SKIP LOCKED``) in friday/db/queue.py
                      (Backend A); swappable for SQS/Redis later.
* ``Outbox``          transactional outbox: enqueue in the SAME DB transaction as the state
                      change (with the Postgres queue the ``jobs`` table IS the outbox:
                      ``enqueue(job, session=s)``).
* ``DistributedLock`` per-user / per-call locks (Postgres advisory locks or Redis).
* ``Cache``           shared non-personal cache (business info, review summaries, IVR maps,
                      pre-rendered TTS). Redis in prod.
* ``RateLimiter``     per-provider rate + concurrency limits (backpressure).
* ``IdempotencyStore`` webhook delivery de-duplication (WhatsApp / telephony retries).

In-memory implementations here are for tests, the simulator and single-process dev.
They are correct within ONE process only.

Owner: Engineering Manager (core). Durable implementations: Backend A (friday/db/).
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from collections import OrderedDict
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from friday.core.clock import Clock, SystemClock, utcnow
from friday.core.models import new_id

if TYPE_CHECKING:  # pragma: no cover
    from friday.core.container import Container


# =============================================================================== jobs


class JobPriority(IntEnum):
    """Lower runs first (founder: live-call & user replies > task steps > proactive > batch)."""

    LIVE = 0  # live-call side effects, user replies, mid-call answers
    TASK = 10  # task-engine steps, calls, call-backs, outbound messages
    PROACTIVE = 20  # nudges, reminders
    BATCH = 30  # fact extraction, vendor memory, analytics


class JobStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    DONE = "done"
    DEAD = "dead"  # dead-letter: exceeded max_attempts or permanently failed


class Job(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=new_id)
    kind: str  # "task.step", "call.place", "message.send", "nudge.evaluate", ...
    payload: dict[str, Any] = Field(default_factory=dict)  # JSON only; ids, not PII blobs
    priority: int = JobPriority.TASK
    due_at: datetime | None = None  # UTC; None = now (queue fills from its Clock)
    dedupe_key: str | None = None  # idempotent enqueue: one live job per key
    partition_key: str | None = None  # e.g. user_id - sharding / per-user ordering
    attempts: int = 0
    max_attempts: int = 8
    status: JobStatus = JobStatus.QUEUED
    claimed_by: str | None = None
    lease_until: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


@runtime_checkable
class JobQueue(Protocol):
    async def enqueue(self, job: Job, *, session: Any = None) -> Job:
        """Idempotent on ``dedupe_key`` (returns the existing QUEUED/CLAIMED job).
        ``session``: enqueue inside the caller's DB transaction (transactional outbox)."""
        ...

    async def claim(
        self,
        worker_id: str,
        *,
        kinds: Sequence[str] | None = None,
        limit: int = 1,
        lease_s: int = 300,
    ) -> list[Job]:
        """Due jobs (due_at <= now), best priority first, each claimed by ONE worker.
        Expired leases are re-claimable (worker crashed)."""
        ...

    async def ack(self, job_id: str) -> None: ...

    async def retry(self, job_id: str, *, error: str, delay_s: float = 30.0) -> Job:
        """attempts += 1; re-queue at now + delay, or DEAD once max_attempts reached."""
        ...

    async def dead_letter(self, job_id: str, *, error: str) -> None: ...

    async def extend_lease(self, job_id: str, lease_s: int) -> None: ...

    async def get(self, job_id: str) -> Job | None: ...

    async def depth(self, *, kinds: Sequence[str] | None = None, due_only: bool = True) -> int:
        """Autoscaling signal."""
        ...


class MemoryJobQueue:
    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or SystemClock()
        self.jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, job: Job, *, session: Any = None) -> Job:
        async with self._lock:
            if job.dedupe_key and (existing_id := self._by_key.get(job.dedupe_key)):
                existing = self.jobs.get(existing_id)
                if existing and existing.status in (JobStatus.QUEUED, JobStatus.CLAIMED):
                    return existing
            if job.due_at is None:
                job.due_at = self.clock.now()
            self.jobs[job.id] = job
            if job.dedupe_key:
                self._by_key[job.dedupe_key] = job.id
            return job

    async def claim(
        self,
        worker_id: str,
        *,
        kinds: Sequence[str] | None = None,
        limit: int = 1,
        lease_s: int = 300,
    ) -> list[Job]:
        now = self.clock.now()
        async with self._lock:
            ready = [
                j
                for j in self.jobs.values()
                if (kinds is None or j.kind in kinds)
                and j.due_at <= now
                and (
                    j.status == JobStatus.QUEUED
                    or (j.status == JobStatus.CLAIMED and j.lease_until and j.lease_until <= now)
                )
            ]
            picked = heapq.nsmallest(
                limit, ready, key=lambda j: (j.priority, j.due_at, j.created_at)
            )
            for j in picked:
                j.status = JobStatus.CLAIMED
                j.claimed_by = worker_id
                j.lease_until = now + timedelta(seconds=lease_s)
            return [j.model_copy() for j in picked]

    async def ack(self, job_id: str) -> None:
        async with self._lock:
            if job := self.jobs.get(job_id):
                job.status = JobStatus.DONE
                job.lease_until = None

    async def retry(self, job_id: str, *, error: str, delay_s: float = 30.0) -> Job:
        async with self._lock:
            job = self.jobs[job_id]
            job.attempts += 1
            job.last_error = error
            job.claimed_by = None
            job.lease_until = None
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.DEAD
            else:
                job.status = JobStatus.QUEUED
                job.due_at = self.clock.now() + timedelta(seconds=delay_s)
            return job.model_copy()

    async def dead_letter(self, job_id: str, *, error: str) -> None:
        async with self._lock:
            job = self.jobs[job_id]
            job.status = JobStatus.DEAD
            job.last_error = error

    async def extend_lease(self, job_id: str, lease_s: int) -> None:
        async with self._lock:
            job = self.jobs[job_id]
            job.lease_until = self.clock.now() + timedelta(seconds=lease_s)

    async def get(self, job_id: str) -> Job | None:
        job = self.jobs.get(job_id)
        return job.model_copy() if job else None

    async def depth(self, *, kinds: Sequence[str] | None = None, due_only: bool = True) -> int:
        now = self.clock.now()
        return sum(
            1
            for j in self.jobs.values()
            if j.status == JobStatus.QUEUED
            and (kinds is None or j.kind in kinds)
            and (not due_only or j.due_at <= now)
        )


# =============================================================================== outbox


class OutboxEntry(BaseModel):
    """A side effect recorded in the same transaction as the state change that caused
    it (send message / place call). The relay turns entries into jobs; consumers must
    be idempotent on ``dedupe_key`` (at-least-once delivery)."""

    id: str = Field(default_factory=new_id)
    kind: str  # "message.send" / "call.place" / ...
    payload: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str
    priority: int = JobPriority.TASK
    due_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)

    def to_job(self) -> Job:
        return Job(
            kind=self.kind,
            payload=self.payload,
            dedupe_key=self.dedupe_key,
            priority=self.priority,
            due_at=self.due_at,
        )


@runtime_checkable
class Outbox(Protocol):
    async def add(self, entry: OutboxEntry, *, session: Any = None) -> None:
        """Record within the caller's transaction (``session``)."""
        ...

    async def relay(self, *, limit: int = 100) -> int:
        """Move committed entries to the JobQueue; returns how many were relayed."""
        ...


class QueueOutbox:
    """Outbox backed directly by a JobQueue (correct when the queue shares the DB
    transaction, i.e. the Postgres queue; best-effort with the memory queue)."""

    def __init__(self, queue: JobQueue) -> None:
        self.queue = queue

    async def add(self, entry: OutboxEntry, *, session: Any = None) -> None:
        await self.queue.enqueue(entry.to_job(), session=session)

    async def relay(self, *, limit: int = 100) -> int:
        return 0


# =============================================================================== locks


class LockTimeout(TimeoutError):
    pass


@runtime_checkable
class DistributedLock(Protocol):
    def hold(self, key: str, *, timeout_s: float = 10.0) -> Any:
        """``async with lock.hold(f"user:{user_id}"):`` - one conversation turn per user.
        Raises LockTimeout if not acquired within ``timeout_s``."""
        ...


class MemoryLock:
    """Per-key asyncio locks with reference counting (no unbounded growth, SECURITY-34)."""

    def __init__(self) -> None:
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def hold(self, key: str, *, timeout_s: float = 10.0) -> AsyncIterator[None]:
        lock, refs = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = (lock, refs + 1)
        try:
            try:
                await asyncio.wait_for(lock.acquire(), timeout=timeout_s)
            except TimeoutError as e:
                raise LockTimeout(key) from e
            try:
                yield
            finally:
                lock.release()
        finally:
            lock, refs = self._locks[key]
            if refs <= 1:
                del self._locks[key]
            else:
                self._locks[key] = (lock, refs - 1)

    def __len__(self) -> int:
        return len(self._locks)


# =============================================================================== cache


@runtime_checkable
class Cache(Protocol):
    """Shared cache of NON-PERSONAL data only. Values must be JSON-serialisable
    (or bytes for pre-rendered audio)."""

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, *, ttl_s: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...


class MemoryCache:
    def __init__(self, clock: Clock | None = None, *, max_entries: int = 10_000) -> None:
        self.clock = clock or SystemClock()
        self.max_entries = max_entries
        self._data: OrderedDict[str, tuple[Any, datetime | None]] = OrderedDict()

    async def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires <= self.clock.now():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    async def set(self, key: str, value: Any, *, ttl_s: int | None = None) -> None:
        expires = self.clock.now() + timedelta(seconds=ttl_s) if ttl_s else None
        self._data[key] = (value, expires)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


# =============================================================================== rate limits


@runtime_checkable
class RateLimiter(Protocol):
    async def acquire(self, key: str, *, cost: float = 1.0, timeout_s: float | None = None) -> bool:
        """Token bucket for ``key`` (e.g. "llm", "telephony", "whatsapp"). Waits up to
        ``timeout_s`` (None = don't wait). False = rate-limited (back off / requeue)."""
        ...

    def slot(self, key: str, *, timeout_s: float | None = None) -> Any:
        """``async with limiter.slot("sarvam"):`` - concurrency cap (live channels,
        STT/TTS streams). Raises LockTimeout if no slot frees up in time."""
        ...


class MemoryRateLimiter:
    def __init__(
        self,
        rates: dict[str, float] | None = None,
        concurrency: dict[str, int] | None = None,
        *,
        clock: Clock | None = None,
        burst_s: float = 1.0,
    ) -> None:
        self.rates = dict(rates or {})
        self.concurrency = dict(concurrency or {})
        self.clock = clock or SystemClock()
        self.burst_s = burst_s
        self._buckets: dict[str, tuple[float, datetime]] = {}
        self._sems: dict[str, asyncio.Semaphore] = {}

    def _take(self, key: str, cost: float) -> float:
        """Returns 0 if taken, else seconds to wait."""
        rate = self.rates.get(key)
        if not rate:
            return 0.0
        capacity = max(rate * self.burst_s, cost)
        now = self.clock.now()
        tokens, last = self._buckets.get(key, (capacity, now))
        tokens = min(capacity, tokens + (now - last).total_seconds() * rate)
        if tokens >= cost:
            self._buckets[key] = (tokens - cost, now)
            return 0.0
        self._buckets[key] = (tokens, now)
        return (cost - tokens) / rate

    async def acquire(self, key: str, *, cost: float = 1.0, timeout_s: float | None = None) -> bool:
        wait = self._take(key, cost)
        if wait == 0.0:
            return True
        if timeout_s is None or wait > timeout_s:
            return False
        await self.clock.sleep(wait)
        return self._take(key, cost) == 0.0

    @asynccontextmanager
    async def slot(self, key: str, *, timeout_s: float | None = None) -> AsyncIterator[None]:
        limit = self.concurrency.get(key)
        if not limit:
            yield
            return
        sem = self._sems.setdefault(key, asyncio.Semaphore(limit))
        try:
            await asyncio.wait_for(sem.acquire(), timeout=timeout_s)
        except TimeoutError as e:
            raise LockTimeout(key) from e
        try:
            yield
        finally:
            sem.release()


# =============================================================================== idempotency


@runtime_checkable
class IdempotencyStore(Protocol):
    async def first_seen(self, key: str, *, ttl_s: int = 72 * 3600) -> bool:
        """Atomically record ``key`` (e.g. "wa:<message id>", "twilio:<CallSid>:<status>").
        True the first time, False for a duplicate delivery (ack and skip)."""
        ...


class MemoryIdempotencyStore:
    def __init__(self, clock: Clock | None = None, *, max_entries: int = 100_000) -> None:
        self._cache = MemoryCache(clock, max_entries=max_entries)

    async def first_seen(self, key: str, *, ttl_s: int = 72 * 3600) -> bool:
        if await self._cache.get(key) is not None:
            return False
        await self._cache.set(key, 1, ttl_s=ttl_s)
        return True


# =============================================================================== factories


def build_memory_job_queue(c: Container) -> MemoryJobQueue:
    return MemoryJobQueue(c.clock)


def build_queue_outbox(c: Container) -> QueueOutbox:
    return QueueOutbox(c.get("job_queue"))


def build_memory_lock(c: Container) -> MemoryLock:
    return MemoryLock()


def build_memory_cache(c: Container) -> MemoryCache:
    return MemoryCache(c.clock)


def build_memory_rate_limiter(c: Container) -> MemoryRateLimiter:
    s = c.settings
    return MemoryRateLimiter(s.provider_rate_per_s, s.provider_concurrency, clock=c.clock)


def build_memory_idempotency(c: Container) -> MemoryIdempotencyStore:
    return MemoryIdempotencyStore(c.clock)


_ids = itertools.count(1)


def worker_id(role: str) -> str:
    """Unique-enough worker id for leases: role-host-pid-n."""
    import os
    import socket

    return f"{role}-{socket.gethostname()}-{os.getpid()}-{next(_ids)}"
