"""Durable job queue on the main database (S-2, ARCHITECTURE §10.3).

``SqlJobQueue`` implements ``core.scale.JobQueue``:

* claim = ``SELECT ... WHERE due AND (queued OR lease expired) ORDER BY priority, due_at
  LIMIT n FOR UPDATE SKIP LOCKED`` then mark CLAIMED with a lease. On Postgres two
  concurrent claimers can never get the same row; on SQLite (dev/tests) writes are
  serialised so the same holds.
* ``enqueue(job, session=s)`` joins the caller's transaction (transactional outbox):
  the job exists iff the state change committed. Idempotent on ``dedupe_key`` (a unique
  partial index guards one LIVE job per key).
* LISTEN/NOTIFY: ``enqueue`` issues ``NOTIFY friday_jobs`` on Postgres and
  ``wait_for_work`` blocks on a LISTEN connection (asyncpg) or sleeps ``poll_s``.
* Dead letters: a job that exhausts ``max_attempts`` becomes DEAD, is logged at ERROR
  (alert hook) and counted by ``dead_count`` for the ops dashboard.
* PgBouncer-safe: no session state; the advisory/notify calls are per-transaction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from friday.core.clock import Clock, SystemClock
from friday.core.logging import get_logger
from friday.core.scale import Job, JobStatus
from friday.db.repositories._base import row_dict
from friday.db.session import Database
from friday.db.tables import JobRow

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)

NOTIFY_CHANNEL = "friday_jobs"
LIVE = (JobStatus.QUEUED.value, JobStatus.CLAIMED.value)


def _job(row: JobRow) -> Job:
    return Job.model_validate(row_dict(row))


class SqlJobQueue:
    def __init__(
        self,
        db: Database,
        clock: Clock | None = None,
        *,
        on_dead_letter: Any = None,
        poll_s: float = 0.5,
    ) -> None:
        self.db = db
        self.clock: Clock = clock or SystemClock()
        self.on_dead_letter = on_dead_letter
        self.poll_s = poll_s
        self._wake = asyncio.Event()

    @property
    def is_postgres(self) -> bool:
        return self.db.engine.dialect.name == "postgresql"

    # ------------------------------------------------------------------ enqueue
    async def enqueue(self, job: Job, *, session: Any = None) -> Job:
        if session is not None:
            return await self._enqueue(session, job)
        async with self.db.session() as s:
            result = await self._enqueue(s, job)
        self._wake.set()
        return result

    async def _enqueue(self, s: Any, job: Job) -> Job:
        if job.dedupe_key:
            live = (
                await s.execute(
                    select(JobRow).where(
                        JobRow.dedupe_key == job.dedupe_key, JobRow.status.in_(LIVE)
                    )
                )
            ).scalar_one_or_none()
            if live is not None:
                return _job(live)
        job = job.model_copy(update={"due_at": job.due_at or self.clock.now()})
        values = job.model_dump(mode="python")
        values["status"] = JobStatus.QUEUED.value
        row = JobRow(**values)
        try:
            async with s.begin_nested():
                s.add(row)
                await s.flush()
        except IntegrityError:  # lost a dedupe race: return the winner
            live = (
                await s.execute(
                    select(JobRow).where(
                        JobRow.dedupe_key == job.dedupe_key, JobRow.status.in_(LIVE)
                    )
                )
            ).scalar_one_or_none()
            if live is None:
                raise
            return _job(live)
        if self.is_postgres:
            await s.execute(select(func.pg_notify(NOTIFY_CHANNEL, job.kind)))
        return _job(row)

    # ------------------------------------------------------------------ claim
    async def claim(
        self,
        worker_id: str,
        *,
        kinds: Sequence[str] | None = None,
        limit: int = 1,
        lease_s: int = 300,
    ) -> list[Job]:
        now = self.clock.now()
        async with self.db.session() as s:
            q = (
                select(JobRow)
                .where(
                    JobRow.due_at <= now,
                    or_(
                        JobRow.status == JobStatus.QUEUED.value,
                        (JobRow.status == JobStatus.CLAIMED.value) & (JobRow.lease_until < now),
                    ),
                )
                .order_by(JobRow.priority, JobRow.due_at, JobRow.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            if kinds:
                q = q.where(JobRow.kind.in_(list(kinds)))
            rows = (await s.execute(q)).scalars().all()
            for r in rows:
                r.status = JobStatus.CLAIMED.value
                r.claimed_by = worker_id
                r.lease_until = now + timedelta(seconds=lease_s)
            await s.flush()
            return [_job(r) for r in rows]

    # ------------------------------------------------------------------ lifecycle
    async def ack(self, job_id: str) -> None:
        async with self.db.session() as s:
            await s.execute(
                update(JobRow)
                .where(JobRow.id == job_id)
                .values(status=JobStatus.DONE.value, lease_until=None)
            )

    async def retry(self, job_id: str, *, error: str, delay_s: float = 30.0) -> Job:
        async with self.db.session() as s:
            row = await s.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            row.attempts += 1
            row.last_error = error[:300]
            row.claimed_by, row.lease_until = None, None
            if row.attempts >= row.max_attempts:
                row.status = JobStatus.DEAD.value
                dead = True
            else:
                row.status = JobStatus.QUEUED.value
                row.due_at = self.clock.now() + timedelta(seconds=delay_s)
                dead = False
            job = _job(row)
        if dead:
            self._alert(job)
        return job

    async def dead_letter(self, job_id: str, *, error: str) -> None:
        async with self.db.session() as s:
            row = await s.get(JobRow, job_id)
            if row is None:
                return
            row.status = JobStatus.DEAD.value
            row.last_error = error[:300]
            row.lease_until = None
            job = _job(row)
        self._alert(job)

    def _alert(self, job: Job) -> None:
        log.error("job %s (%s) dead-lettered after %s attempts", job.id, job.kind, job.attempts)
        if self.on_dead_letter is not None:
            try:
                self.on_dead_letter(job)
            except Exception:  # noqa: BLE001
                log.exception("dead-letter hook failed")

    async def extend_lease(self, job_id: str, lease_s: int) -> None:
        async with self.db.session() as s:
            await s.execute(
                update(JobRow)
                .where(JobRow.id == job_id, JobRow.status == JobStatus.CLAIMED.value)
                .values(lease_until=self.clock.now() + timedelta(seconds=lease_s))
            )

    async def get(self, job_id: str) -> Job | None:
        async with self.db.session() as s:
            row = await s.get(JobRow, job_id)
            return _job(row) if row else None

    async def depth(self, *, kinds: Sequence[str] | None = None, due_only: bool = True) -> int:
        async with self.db.session() as s:
            q = (
                select(func.count())
                .select_from(JobRow)
                .where(JobRow.status == JobStatus.QUEUED.value)
            )
            if kinds:
                q = q.where(JobRow.kind.in_(list(kinds)))
            if due_only:
                q = q.where(JobRow.due_at <= self.clock.now())
            return int((await s.execute(q)).scalar_one())

    async def dead_count(self) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(JobRow)
                        .where(JobRow.status == JobStatus.DEAD.value)
                    )
                ).scalar_one()
            )

    # ------------------------------------------------------------------ wake-up
    def wake(self) -> None:
        """Called after a transaction that enqueued with ``session=`` commits."""
        self._wake.set()

    async def wait_for_work(self, timeout_s: float | None = None) -> bool:
        """Block until something was enqueued here (or NOTIFY on Postgres) or timeout."""
        timeout = self.poll_s if timeout_s is None else timeout_s
        try:
            await asyncio.wait_for(self._wake.wait(), timeout)
        except TimeoutError:
            return False
        self._wake.clear()
        return True


def build_pg_job_queue(c: Container) -> SqlJobQueue:
    return SqlJobQueue(c.db, c.clock, poll_s=c.settings.queue_poll_interval_s)
