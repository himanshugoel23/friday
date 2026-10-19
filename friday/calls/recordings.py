"""Recording retention and deletion (A4.5).

* Default retention 30 days (``FRIDAY_CALLS_RECORDING_RETENTION_DAYS``), then the object is deleted
  and the reference cleared. A recording is never announced on the call (founder decision, legal
  read pending: docs/LEGAL_MAP.md).
* The user can list their own recordings and delete one at once; a request for another user's
  recording finds nothing (``RecordingNotFound``), never "forbidden", so existence is not leaked.
* ``ObjectDeleter`` is the existing ``friday.db.objectstore.delete_recording`` (or the store's
  ``delete``); tests pass a fake.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from friday.calls.settings import CallsSettings
from friday.calls.stores import CallStore, RecordingRecord
from friday.core.clock import Clock, SystemClock
from friday.core.logging import get_logger

log = get_logger(__name__)

ObjectDeleter = Callable[[str], Awaitable[bool]]


class RecordingNotFound(LookupError):
    pass


class RecordingService:
    def __init__(
        self,
        store: CallStore,
        deleter: ObjectDeleter,
        settings: CallsSettings | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.store, self.deleter = store, deleter
        self.settings = settings or CallsSettings()
        self.clock: Clock = clock or SystemClock()

    @property
    def retention(self) -> timedelta:
        return timedelta(days=self.settings.recording_retention_days)

    def expires_at(self, rec: RecordingRecord) -> datetime:
        return rec.created_at + self.retention

    async def list_for_user(self, user_id: str) -> list[RecordingRecord]:
        return await self.store.recordings(user_id)

    async def delete_now(self, user_id: str, ref: str) -> bool:
        """Delete the user's own recording at once. Anyone else's looks like 'not found'."""
        own = {r.ref for r in await self.store.recordings(user_id)}
        if ref not in own:
            raise RecordingNotFound(ref)
        ok = await self.deleter(ref)
        if ok:
            await self.store.clear_recording(user_id, ref)
        else:
            log.warning("recording delete failed for a user's recording; will retry on next sweep")
        return ok

    async def purge_expired(self, now: datetime | None = None) -> int:
        """Delete every recording older than the retention. Returns how many were removed."""
        cutoff = (now or self.clock.now()) - self.retention
        n = 0
        for rec in await self.store.recordings_before(cutoff):
            if await self.deleter(rec.ref):
                await self.store.clear_recording(rec.user_id, rec.ref)
                n += 1
        return n

    async def purge_user(self, user_id: str) -> int:
        """Erasure of a user: every recording of theirs (called by DataPurger's flow)."""
        n = 0
        for rec in await self.store.recordings(user_id):
            if await self.deleter(rec.ref):
                await self.store.clear_recording(user_id, rec.ref)
                n += 1
        return n
