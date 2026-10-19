"""Recording retention (default 30 days), delete-now, per-user access only."""

from __future__ import annotations

from datetime import timedelta

import pytest

from friday.calls.models import CallOutcome, OutcomeStatus
from friday.calls.recordings import RecordingNotFound, RecordingService
from friday.calls.settings import CallsSettings
from friday.calls.stores import MemoryCallStore
from friday.core.clock import FakeClock


class Deleter:
    def __init__(self, ok=True):
        self.deleted: list[str] = []
        self.ok = ok

    async def __call__(self, ref: str) -> bool:
        if self.ok:
            self.deleted.append(ref)
        return self.ok


async def seed(store: MemoryCallStore, clock: FakeClock):
    for uid, rid, ref, age_days in (
        ("u1", "r1", "s3://b/u1-old.wav", 31),
        ("u1", "r2", "s3://b/u1-new.wav", 3),
        ("u2", "r3", "s3://b/u2-old.wav", 45),
    ):
        o = CallOutcome(
            request_id=rid, status=OutcomeStatus.COMPLETED, recording_ref=ref,
            started_at=clock.now() - timedelta(days=age_days),
        )  # fmt: skip
        await store.add_outcome(uid, o, "h")


def test_default_retention_is_30_days():
    assert CallsSettings().recording_retention_days == 30


async def test_purge_expired_deletes_only_old_recordings():
    clock, store, d = FakeClock(), MemoryCallStore(), Deleter()
    await seed(store, clock)
    svc = RecordingService(store, d, clock=clock)
    assert await svc.purge_expired() == 2
    assert sorted(d.deleted) == ["s3://b/u1-old.wav", "s3://b/u2-old.wav"]
    assert [r.ref for r in await store.recordings("u1")] == ["s3://b/u1-new.wav"]
    assert await svc.purge_expired() == 0  # nothing left to do


async def test_retention_is_a_setting():
    clock, store, d = FakeClock(), MemoryCallStore(), Deleter()
    await seed(store, clock)
    svc = RecordingService(store, d, CallsSettings(recording_retention_days=2), clock)
    assert await svc.purge_expired() == 3


async def test_delete_now_is_per_user():
    clock, store, d = FakeClock(), MemoryCallStore(), Deleter()
    await seed(store, clock)
    svc = RecordingService(store, d, clock=clock)
    with pytest.raises(RecordingNotFound):
        await svc.delete_now("u1", "s3://b/u2-old.wav")  # someone else's: looks like not found
    assert d.deleted == []
    assert await svc.delete_now("u1", "s3://b/u1-new.wav")
    assert d.deleted == ["s3://b/u1-new.wav"]
    assert [r.ref for r in await svc.list_for_user("u1")] == ["s3://b/u1-old.wav"]
    assert [r.ref for r in await svc.list_for_user("u2")] == ["s3://b/u2-old.wav"]


async def test_failed_delete_keeps_the_reference_for_the_next_sweep():
    clock, store, d = FakeClock(), MemoryCallStore(), Deleter(ok=False)
    await seed(store, clock)
    svc = RecordingService(store, d, clock=clock)
    assert await svc.purge_expired() == 0
    assert len(await store.recordings("u1")) == 2
    d.ok = True
    assert await svc.purge_expired() == 2


async def test_purge_user_for_erasure():
    clock, store, d = FakeClock(), MemoryCallStore(), Deleter()
    await seed(store, clock)
    svc = RecordingService(store, d, clock=clock)
    assert await svc.purge_user("u1") == 2
    assert await store.recordings("u1") == [] and len(await store.recordings("u2")) == 1
