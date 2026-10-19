"""now_status across boundaries and quiet hours; the context summary leaks nothing private."""

from __future__ import annotations

from datetime import datetime

from friday.core.clock import IST
from friday.core.config import Settings
from friday.lifestate.conversation import (
    LifeContextProvider,
    get_context_provider,
    register_context_provider,
)
from friday.lifestate.models import EventKind, EventStatus, LifeEvent, NowState
from friday.lifestate.now import busy_until, compute_now_status, context_summary, now_status
from friday.lifestate.ports import BillRef


def t(h: int, m: int = 0, day: int = 19, s: int = 0) -> datetime:
    return datetime(2026, 10, day, h, m, s, tzinfo=IST)


def ev(user, kind, start, end, **kw) -> LifeEvent:
    return LifeEvent(
        user_id=user,
        title=kw.pop("title", kind.value),
        start=start,
        end=end,
        kind=kind,
        protected=kw.pop("protected", kind != EventKind.PERSONAL),
        **kw,
    )


def test_event_boundaries_start_inclusive_end_exclusive():
    e = ev("u", EventKind.INTERVIEW, t(14), t(15))
    assert compute_now_status([e], t(13, 59, s=59)).state == NowState.FREE
    s = compute_now_status([e], t(14))
    assert s.state == NowState.IN_EVENT and s.kind == EventKind.INTERVIEW
    assert s.ends_at == t(15) and s.protected
    assert compute_now_status([e], t(14, 59, s=59)).state == NowState.IN_EVENT
    assert compute_now_status([e], t(15)).state == NowState.FREE


def test_quiet_hours_boundaries_default_22_to_8():
    assert compute_now_status([], t(21, 59)).state == NowState.FREE
    s = compute_now_status([], t(22))
    assert s.state == NowState.QUIET_HOURS and s.ends_at == t(8, day=20)
    assert compute_now_status([], t(7, 59)).state == NowState.QUIET_HOURS
    assert compute_now_status([], t(8)).state == NowState.FREE
    assert compute_now_status([], t(0, 30)).ends_at == t(8)


def test_custom_quiet_hours():
    assert compute_now_status([], t(23), quiet_start=23, quiet_end=6).state == NowState.QUIET_HOURS
    assert compute_now_status([], t(22), quiet_start=23, quiet_end=6).state == NowState.FREE


def test_travel_beats_quiet_hours():
    e = ev("u", EventKind.TRAVEL, t(21), t(23, 30))
    s = compute_now_status([e], t(22, 30))
    assert s.state == NowState.TRAVELLING and s.ends_at == t(23, 30)


def test_back_to_back_events_chain():
    a = ev("u", EventKind.MEETING, t(14), t(15))
    b = ev("u", EventKind.INTERVIEW, t(15), t(16))
    assert busy_until([a, b], t(14, 30)) == t(16)
    assert compute_now_status([a, b], t(14, 30)).ends_at == t(16)
    assert busy_until([a, b], t(16)) is None


def test_gap_does_not_chain():
    a = ev("u", EventKind.MEETING, t(14), t(15))
    b = ev("u", EventKind.MEETING, t(15, 5), t(16))
    assert busy_until([a, b], t(14, 30)) == t(15)


def test_cancelled_done_and_bills_do_not_occupy():
    a = ev("u", EventKind.MEETING, t(14), t(15), status=EventStatus.CANCELLED)
    b = ev("u", EventKind.BILL_DUE, t(14), t(15))
    c = ev("u", EventKind.MEETING, t(14), t(15), status=EventStatus.DONE)
    assert compute_now_status([a, b, c], t(14, 30)).state == NowState.FREE


def test_protected_overlap_wins():
    loose = ev("u", EventKind.PERSONAL, t(14), t(17), protected=False)
    tight = ev("u", EventKind.INTERVIEW, t(14, 30), t(15))
    s = compute_now_status([loose, tight], t(14, 45))
    assert s.kind == EventKind.INTERVIEW and s.protected


async def test_now_status_from_store_with_settings(world):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(14), t(15)))
    st = Settings(_env_file=None, quiet_hours_start=23, quiet_hours_end=7)
    assert (await now_status(world.store, world.u1, t(14, 30), st)).state == NowState.IN_EVENT
    assert (await now_status(world.store, world.u1, t(22, 30), st)).state == NowState.FREE
    assert (await now_status(world.store, world.u1, t(23, 30), st)).state == NowState.QUIET_HOURS
    # another user is unaffected
    assert (await now_status(world.store, world.u2, t(14, 30), st)).state == NowState.FREE


async def test_overnight_event_still_covers_after_midnight(world):
    await world.store.save_event(ev(world.u1, EventKind.TRAVEL, t(23), t(6, day=20)))
    s = await now_status(world.store, world.u1, t(3, day=20))
    assert s.state == NowState.TRAVELLING


async def test_context_summary_has_no_private_text(world):
    secret_title = "Interview at Acme about project Zephyr salary 40 lakh"
    await world.store.save_event(
        ev(
            world.u1,
            EventKind.INTERVIEW,
            t(14),
            t(15),
            title=secret_title,
            location="Acme Tower, Sector 62",
            note="they will ask about my layoffs",
        )
    )
    await world.store.save_event(ev(world.u1, EventKind.BILL_DUE, t(9, day=21), t(9, day=21)))
    await world.store.save_event(ev(world.u1, EventKind.BILL_DUE, t(9, day=23), t(9, day=23)))
    s = await context_summary(world.store, world.u1, t(14, 30))
    assert "interview" in s and "15:00" in s and "bills due this week: 2" in s
    assert "protected" in s
    for leak in ("Acme", "Zephyr", "salary", "lakh", "Sector", "layoffs"):
        assert leak not in s


async def test_context_summary_free_and_other_user_empty(world):
    await world.store.save_event(ev(world.u1, EventKind.MEETING, t(17), t(18)))
    s1 = await context_summary(world.store, world.u1, t(12))
    assert s1.startswith("now: free") and "next: meeting at 17:00 IST" in s1
    s2 = await context_summary(world.store, world.u2, t(12))
    assert "meeting" not in s2


async def test_bills_port_adds_to_count(world):
    class Bills:
        async def pending_bills(self, user_id, now):
            return [
                BillRef("b1", datetime(2026, 10, 22).date()),
                BillRef("b2", datetime(2026, 12, 1).date()),
            ]

    s = await context_summary(world.store, world.u1, t(12), bills=Bills())
    assert "bills due this week: 1" in s


async def test_provider_and_registration_point(world):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(14), t(15)))
    p = LifeContextProvider(world.store)
    register_context_provider(p)
    try:
        assert get_context_provider() is p
        assert "interview" in await get_context_provider().context_for(world.u1, t(14, 10))
        st = await p.status_for(world.u1, t(14, 10))
        assert st.busy and st.protected
        snap = await p.snapshot_for(world.u1, t(14, 10))
        assert snap.events_today == 1
    finally:
        register_context_provider(None)
    assert get_context_provider() is None
