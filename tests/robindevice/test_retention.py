"""T03: device retention with a fake clock. Events 7 d, call-pattern cues per ``call_text_retain_days``, abandoned analyzers."""

from __future__ import annotations

from friday.robindevice.ports import CONSENT_ITEMS, FakeAlertPort, InMemoryConsent, InMemoryParents
from friday.robindevice.service import DAY_MS, EVENT_RETAIN_DAYS, DeviceService
from friday.robindevice.store import Event
from tests.robindevice.conftest import Clock, ist_ms


def make(retain: int = 0):
    clock = Clock(ist_ms(2026, 9, 9, 14, 0))
    consent, parents = InMemoryConsent(), InMemoryParents()
    parents.add("p1", "en")
    consent.grant_all("p1", CONSENT_ITEMS)
    return clock, DeviceService(alerts=FakeAlertPort(), consent=consent, parents=parents, now_ms=clock, call_text_retain_days=retain)


def ev(i: str, typ: str, age_days: float, clock: Clock) -> Event:
    return Event(i, typ, int(clock.ms - age_days * DAY_MS), {})


async def test_events_are_kept_exactly_seven_days():
    assert EVENT_RETAIN_DAYS == 7
    clock, svc = make()
    st = svc.store.state("p1")
    st.events = [ev("a", "camera_in_use_start", 7.1, clock), ev("b", "camera_in_use_start", 6.9, clock), ev("c", "call_started", 30, clock)]
    assert await svc.retention() == 2
    assert [e.id for e in st.events] == ["b"]
    assert await svc.retention() == 0  # idempotent


async def test_call_pattern_cues_follow_call_text_retain_days():
    clock, svc = make(retain=3)
    st = svc.store.state("p1")
    st.events = [ev("a", "call_pattern", 3.5, clock), ev("b", "call_pattern", 2.5, clock), ev("c", "camera_in_use_start", 5, clock)]
    await svc.retention()
    assert sorted(e.id for e in st.events) == ["b", "c"]
    clock2, svc2 = make(retain=0)  # nothing retained: cues live one day only
    st2 = svc2.store.state("p1")
    st2.events = [ev("a", "call_pattern", 1.2, clock2), ev("b", "call_pattern", 0.5, clock2)]
    await svc2.retention()
    assert [e.id for e in st2.events] == ["b"]


async def test_sweep_runs_the_retention_and_an_abandoned_analyzer_is_dropped():
    clock, svc = make()
    svc.store.state("p1").events = [ev("a", "camera_in_use_start", 9, clock)]
    await svc.feed_call_turn("p1", "call-x", "caller", "police bol raha hoon", 1.0)
    assert ("p1", "call-x") in svc._analyzers
    clock.advance(hours=30)
    await svc.sweep()
    assert svc.store.state("p1").events == [] and svc._analyzers == {} and svc._analyzer_ms == {}


async def test_a_finished_call_leaves_no_analyzer_bookkeeping():
    clock, svc = make()
    await svc.feed_call_turn("p1", "call-y", "caller", "police bol raha hoon", 1.0)
    assert svc.finish_call("p1", "call-y") is not None and svc._analyzer_ms == {}
