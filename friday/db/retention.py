"""Retention + deferred erasure (SECURITY-32, SECURITY-14).

``run_retention`` is the daily job body (scheduled by Backend B's queue/scheduler):

* recordings older than ``recording_days`` (30): object deleted, ``calls.recording_url``
  cleared; transcript turns deleted and mid-call question/answer text blanked
  (task summaries/results are kept);
* pre-consent users (never agreed to the DPDP notice) older than ``preconsent_days``
  (7): purged like "delete everything";
* ephemeral "current location" places older than 24 h: deleted;
* ``pending_deletions`` (erasures that failed earlier): retried, given up after 20.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update

from friday.core.models import ConsentKind, UserStatus
from friday.db.objectstore import ObjectStore, delete_recording
from friday.db.repositories import Repositories
from friday.db.tables import (
    CallQuestionRow,
    CallRow,
    CallTurnRow,
    ConsentRow,
    PendingDeletionRow,
    PlaceRow,
    UserRow,
)

RECORDING_RETENTION_DAYS = 30
PRECONSENT_RETENTION_DAYS = 7
EPHEMERAL_PLACE_HOURS = 24
MAX_DELETION_ATTEMPTS = 20


async def add_pending_deletion(repos: Repositories, url: str, *, error: str | None = None) -> None:
    async with repos.db.session() as s:
        s.add(PendingDeletionRow(url=url, attempts=1, last_error=(error or "")[:200] or None))


async def pending_deletions(repos: Repositories) -> list[tuple[str, str]]:
    async with repos.db.session() as s:
        rows = (await s.execute(select(PendingDeletionRow))).scalars()
        return [(r.id, r.url) for r in rows]


async def erase_recordings(
    repos: Repositories, urls: list[str], *, store: ObjectStore, telephony: Any = None
) -> int:
    """Delete each URL; failures go to ``pending_deletions``. Returns deleted count."""
    done = 0
    for url in urls:
        if await delete_recording(url, store=store, telephony=telephony):
            done += 1
        else:
            await add_pending_deletion(repos, url, error="delete failed")
    return done


async def process_pending_deletions(
    repos: Repositories, *, store: ObjectStore, telephony: Any = None
) -> int:
    done = 0
    async with repos.db.session() as s:
        rows = (await s.execute(select(PendingDeletionRow))).scalars().all()
        for row in rows:
            if await delete_recording(row.url, store=store, telephony=telephony):
                await s.delete(row)
                done += 1
            else:
                row.attempts += 1
                if row.attempts >= MAX_DELETION_ATTEMPTS:
                    row.last_error = "gave up (ops: delete manually)"
    return done


async def expire_recordings(
    repos: Repositories,
    now: datetime,
    *,
    store: ObjectStore,
    telephony: Any = None,
    days: int = RECORDING_RETENTION_DAYS,
) -> dict[str, int]:
    cutoff = now - timedelta(days=days)
    async with repos.db.session() as s:
        calls = (
            await s.execute(
                select(CallRow.id, CallRow.recording_url).where(CallRow.started_at < cutoff)
            )
        ).all()
        call_ids = [c.id for c in calls]
        urls = [c.recording_url for c in calls if c.recording_url]
        turns = 0
        if call_ids:
            res = await s.execute(delete(CallTurnRow).where(CallTurnRow.call_id.in_(call_ids)))
            turns = int(res.rowcount or 0)
            await s.execute(
                update(CallQuestionRow)
                .where(CallQuestionRow.call_id.in_(call_ids))
                .values(text="[expired]", answer_text=None)
            )
            await s.execute(
                update(CallRow).where(CallRow.id.in_(call_ids)).values(recording_url=None)
            )
    deleted = await erase_recordings(repos, urls, store=store, telephony=telephony)
    return {"recordings": deleted, "call_turns": turns}


async def purge_preconsent_users(
    repos: Repositories, now: datetime, *, days: int = PRECONSENT_RETENTION_DAYS
) -> int:
    cutoff = now - timedelta(days=days)
    async with repos.db.session() as s:
        consented = select(ConsentRow.user_id).where(
            ConsentRow.kind == ConsentKind.TERMS_PRIVACY.value, ConsentRow.granted.is_(True)
        )
        ids = (
            (
                await s.execute(
                    select(UserRow.id).where(
                        UserRow.status.in_(
                            [UserStatus.ONBOARDING.value, UserStatus.WAITLISTED.value]
                        ),
                        UserRow.created_at < cutoff,
                        UserRow.id.not_in(consented),
                    )
                )
            )
            .scalars()
            .all()
        )
    for uid in ids:
        await repos.purger.purge_user(uid)
    return len(ids)


async def delete_ephemeral_places(
    repos: Repositories, now: datetime, *, hours: int = EPHEMERAL_PLACE_HOURS
) -> int:
    async with repos.db.session() as s:
        res = await s.execute(
            delete(PlaceRow).where(
                PlaceRow.ephemeral.is_(True), PlaceRow.created_at < now - timedelta(hours=hours)
            )
        )
        return int(res.rowcount or 0)


async def run_retention(
    repos: Repositories,
    now: datetime,
    *,
    store: ObjectStore,
    telephony: Any = None,
    recording_days: int = RECORDING_RETENTION_DAYS,
    preconsent_days: int = PRECONSENT_RETENTION_DAYS,
) -> dict[str, int]:
    out = await expire_recordings(repos, now, store=store, telephony=telephony, days=recording_days)
    out["preconsent_users"] = await purge_preconsent_users(repos, now, days=preconsent_days)
    out["ephemeral_places"] = await delete_ephemeral_places(repos, now)
    out["pending_deletions"] = await process_pending_deletions(
        repos, store=store, telephony=telephony
    )
    return out


class RetentionService:
    """``repos.retention.run(now, recording_days, preconsent_days)`` (Backend B's daily job).

    The object store and telephony provider are resolved lazily so building the
    repository bundle never needs them."""

    def __init__(self, repos: Repositories, store_factory: Any, telephony_factory: Any = None):
        self._repos = repos
        self._store_factory = store_factory
        self._telephony_factory = telephony_factory

    async def run(
        self,
        now: datetime,
        recording_days: int = RECORDING_RETENTION_DAYS,
        preconsent_days: int = PRECONSENT_RETENTION_DAYS,
    ) -> dict[str, int]:
        telephony = self._telephony_factory() if self._telephony_factory else None
        return await run_retention(
            self._repos,
            now,
            store=self._store_factory(),
            telephony=telephony,
            recording_days=recording_days,
            preconsent_days=preconsent_days,
        )
