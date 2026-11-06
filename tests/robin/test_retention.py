# ruff: noqa: E501
"""T03: retention jobs run from the Robin scheduler (``RobinHub.tick``) and delete ONLY what is older than the limit.
Audit 30 d, closed incident records 90 d (proposed default, setting ``robin_incident_retention_days``), device events 7 d,
call-pattern cues per ``call_text_retain_days``. Fake clock, fakes only."""

from __future__ import annotations

from datetime import timedelta

from friday.robin.store import Record
from friday.robin.wiring import PURGE_EVERY_TICKS
from tests.robin.test_erase_all import Phone

DAY_MS = 86_400_000


async def put(w, fam, kind, days_old, status="closed", key=None):
    return (await w.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind=kind, key=key, status=status, at=w.clock.now() - timedelta(days=days_old), data={"event": "x", "text": "t"})))[0]


async def run_retention_tick(w):
    w.hub._ticks = PURGE_EVERY_TICKS - 1  # the next tick is the purge tick
    await w.hub.tick()


async def test_audit_rows_older_than_30_days_go_and_younger_stay(w):
    fam, _ = await w.family()
    old, young = await put(w, fam, "audit", 31, key="a-old"), await put(w, fam, "audit", 29, key="a-young")
    await run_retention_tick(w)
    assert await w.store.get(old.id) is None and await w.store.get(young.id) is not None


async def test_closed_incidents_after_90_days_but_never_an_open_one(w):
    assert w.hub.incident_retention_days == 90  # the proposed default
    fam, _ = await w.family()
    old_closed, young_closed = await put(w, fam, "incident", 91, "closed", "i1"), await put(w, fam, "incident", 89, "closed", "i2")
    old_exhausted, old_open = await put(w, fam, "incident", 120, "exhausted", "i3"), await put(w, fam, "incident", 120, "open", "i4")
    await run_retention_tick(w)
    alive = {n: await w.store.get(r.id) is not None for n, r in dict(oc=old_closed, yc=young_closed, oe=old_exhausted, oo=old_open).items()}
    assert alive == {"oc": False, "yc": True, "oe": False, "oo": True}


async def test_retention_only_runs_on_the_purge_tick(w):
    fam, _ = await w.family()
    old = await put(w, fam, "audit", 40, key="a")
    await w.hub.tick()
    assert await w.store.get(old.id) is not None  # not yet the purge tick
    await run_retention_tick(w)
    assert await w.store.get(old.id) is None


async def test_the_setting_drives_the_incident_limit(w):
    w.hub.incident_retention_days = 10
    fam, _ = await w.family()
    gone, kept = await put(w, fam, "incident", 11, "closed", "i1"), await put(w, fam, "incident", 9, "closed", "i2")
    await run_retention_tick(w)
    assert await w.store.get(gone.id) is None and await w.store.get(kept.id) is not None


async def test_device_events_and_cues_are_cleaned_by_the_same_tick(w, db):
    from friday.robindevice.store import Event

    fam, parent = await w.family()
    for item in ("device_signals", "call_listening"):
        await w.hub.fam.admin_consent(fam, item)
    phone = Phone(w, db)
    await phone.pair(parent.id)
    w.hub.attach_device_sweep(phone.service.sweep)
    now = int(w.clock.now().timestamp() * 1000)
    st = phone.store.state(parent.id)
    st.events = [
        Event("old", "camera_in_use_start", now - 8 * DAY_MS, {}), Event("young", "camera_in_use_start", now - DAY_MS // 2, {}),
        Event("cp-old", "call_pattern", now - 30 * 3_600_000, {"call_id": "c1", "tier": "WATCH", "score": 3, "cue_ids": ["x"]}),
        Event("cp-young", "call_pattern", now - 3_600_000, {"call_id": "c2", "tier": "WATCH", "score": 3, "cue_ids": ["x"]}),
    ]
    phone.store.touch(parent.id)
    await w.hub.tick()
    assert sorted(e.id for e in phone.store.state(parent.id).events) == ["cp-young", "young"]  # cues: 1 day when call_text_retain_days is 0
    await phone.client.aclose()
