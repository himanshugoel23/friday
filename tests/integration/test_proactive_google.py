"""One proactive tick for bills and follow-ups under the same caps, the dedupe between W3 and W4,
the Google calendar sync behind its switch, and the clash check against a live calendar."""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.core.clock import IST
from friday.core.models import NudgeCandidate
from friday.integration.proactive import LifeFollowupSource, topic_of_key
from friday.lifestate.models import EventKind, EventSource
from tests.google.conftest import connect_user
from tests.integration.conftest import World, close_world, make_world

BILL = "Your electricity bill of Rs 1,240.50 for BSES is due on 25 Jan 2026."


def sent_to(w: World, since: int) -> list[str]:
    return [m.text or "" for m in w.channel.messages_to(w.phone)[since:]]


# ------------------------------------------------------------------------------- one tick
async def test_one_tick_produces_both_kinds_under_one_cap(world: World):
    await world.say(BILL)
    await world.tap("Sahi")
    await world.say("parso 2 baje interview hai")  # Jan 7, 14:00-15:00
    world.set_time(world.at(15, 45, day=7))  # the interview is over, the bill is 18 days away
    before = len(world.channel.messages_to(world.phone))
    out = await world.tick()
    assert len(out) == 1  # the follow-up after the interview; the far-off bill is silent
    world.set_time(world.at(9, 5, day=22))  # d3 of the bill
    await world.tick()
    texts = sent_to(world, before)
    assert any("interview" in t.lower() for t in texts) and any("BSES" in t for t in texts)


async def test_w3_owns_the_bill_so_a_w4_bill_for_the_same_day_is_not_reminded_twice(world: World):
    await world.say(BILL)
    await world.tap("Sahi")
    # the same bill, also known to the life state (e.g. from the calendar or an earlier chat)
    from friday.lifestate.models import LifeEvent

    await world.consumer.life.store.save_event(
        LifeEvent(
            user_id=world.user.id, title="bijli bill", start=world.at(9, 0, day=25),
            end=world.at(9, 0, day=25), kind=EventKind.BILL_DUE, source=EventSource.USER,
        )
    )  # fmt: skip
    world.set_time(world.at(10, 30, day=23))  # W4's own bill nudge time
    alone = LifeFollowupSource(world.consumer.life.store, world.c.settings, world.clock)
    assert [c.dedupe_key for c in await alone(world.user.id, world.clock.now())]  # W4 alone would
    shared = world.consumer.extras["life_source"]
    assert await shared(world.user.id, world.clock.now()) == []  # with W3's bills it stays out
    before = len(world.channel.messages_to(world.phone))
    for day, hour in ((22, 9), (23, 10), (24, 9), (25, 9)):
        world.set_time(world.at(hour, 30, day=day))
        await world.tick()
    bill_msgs = [t for t in sent_to(world, before) if "bill" in t.lower()]
    assert len(bill_msgs) == 3  # d3, d1, d0 from W3 only: not six


async def test_the_approved_text_and_the_buttons_survive_the_quiet_hours_hold(world: World):
    await world.say(BILL)
    await world.tap("Sahi")
    world.set_time(world.at(23, 0, day=24))
    await world.tick()
    world.set_time(world.at(8, 5, day=25))
    await world.tick()
    last = world.channel.last_to(world.phone)
    assert last is not None and "BSES" in (last.text or "")
    assert any(b.id.startswith("bill:") for b in last.buttons)  # the bill buttons, not generic ones


async def test_followup_is_recorded_as_sent_so_the_reply_is_understood(world: World):
    await world.say("kal 2 baje interview hai")
    world.set_time(world.at(15, 45, day=6))
    await world.tick()
    follow = await world.consumer.life.store.list_followups(world.user.id)
    assert [f.status for f in follow] == ["sent"] and follow[0].topic.startswith("after_event")


async def test_a_broken_source_does_not_silence_the_others(world: World, caplog):
    engine = world.c.get("proactive")

    async def broken(user_id: str, now: datetime) -> list[NudgeCandidate]:
        raise RuntimeError("boom")

    engine.register_source(broken)
    await world.say("kal 2 baje interview hai")
    world.set_time(world.at(15, 45, day=6))
    out = await engine.tick()
    assert len(out) == 1
    assert "proactive source" in caplog.text  # logged, by type of source, never silent
    caplog.clear()  # this failure is expected here


def test_topic_of_key():
    assert topic_of_key("after:e1:100", EventKind.INTERVIEW) == ("after_event:interview", "e1")
    assert topic_of_key("before:e1:100", EventKind.MEETING) == ("before_event:meeting", "e1")
    assert topic_of_key("commit:c1:100", None) == ("commitment", None)


async def test_sources_registered_only_for_the_switches_that_are_on():
    w = await make_world(calls=True, savings=False, lifestate=False)
    try:
        engine = w.c.get("proactive")
        assert engine._sources == [] and engine._briefing_providers == []
    finally:
        await close_world(w)
    w = await make_world(calls=False, savings=True, lifestate=False)
    try:
        engine = w.c.get("proactive")
        assert len(engine._sources) == 1 and engine._briefing_providers == []
    finally:
        await close_world(w)


async def test_life_source_skips_a_topic_the_user_muted(world: World):
    await world.say("kal 2 baje interview hai")
    await world.consumer.life.store.set_topic(world.user.id, "after_event", muted=True)
    world.set_time(world.at(15, 45, day=6))
    src: LifeFollowupSource = world.consumer.extras["life_source"]
    assert await src(world.user.id, world.clock.now()) == []


# ------------------------------------------------------------------------------- Google sync
async def _google_world() -> World:
    w = await make_world(calls=False, savings=False, lifestate=True, google=True)
    assert w.fake_google is not None
    await connect_user(w.consumer.google.oauth(), w.fake_google, w.user.id)
    return w


def _add_event(w: World, eid: str, summary: str, start: datetime, hours: int = 1) -> None:
    assert w.fake_google is not None
    w.fake_google.events.setdefault("sub-alice", {})[eid] = {
        "id": eid,
        "summary": summary,
        "status": "confirmed",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(hours=hours)).isoformat()},
    }


async def test_calendar_sync_imports_events_behind_the_google_switch():
    w = await _google_world()
    try:
        _add_event(w, "ev1", "Interview with ACME", datetime(2026, 1, 6, 14, 0, tzinfo=IST))
        out = await w.consumer.periodic()
        assert out["calendar_sync"] == 1
        assert (await w.consumer.sync_calendars()) == 0  # at most every 15 minutes
        events = await w.consumer.life.store.list_events(w.user.id)
        assert [(e.source, e.kind) for e in events] == [(EventSource.CALENDAR, EventKind.INTERVIEW)]
        # the title is untrusted text: it never reaches the summary the brain gets
        w.set_time(w.at(14, 30, day=6))
        summary = await w.consumer.context_summary(w.user.id)
        assert summary and "interview" in summary and "ACME" not in summary
        assert (await w.consumer.sync_calendars()) == 1  # hours later: read again
    finally:
        await close_world(w)


async def test_sync_follows_a_change_and_skips_a_disconnected_user():
    w = await _google_world()
    try:
        _add_event(w, "ev1", "Standup meeting", datetime(2026, 1, 6, 11, 0, tzinfo=IST))
        await w.consumer.sync_calendars()
        w.fake_google.events["sub-alice"]["ev1"]["status"] = "cancelled"  # type: ignore[union-attr]
        w.set_time(w.at(10, 30))
        await w.consumer.sync_calendars()
        events = await w.consumer.life.store.list_events(w.user.id, include_inactive=False)
        assert events == []  # cancelled in the calendar, cancelled here
        await w.consumer.google.oauth().disconnect(w.user.id)
        w.set_time(w.at(11, 30))
        assert (await w.consumer.sync_calendars()) == 0  # no connection, nothing read
    finally:
        await close_world(w)


async def test_clash_check_reads_the_live_calendar_when_a_booking_time_is_proposed():
    w = await _google_world()
    try:
        _add_event(w, "ev9", "Dentist", datetime(2026, 1, 6, 17, 0, tzinfo=IST))
        note = await w.consumer.clash_note(w.user.id, datetime(2026, 1, 6, 17, 30, tzinfo=IST))
        assert note  # not synced yet, but the live read finds the collision
        assert await w.consumer.clash_note(w.user.id, datetime(2026, 1, 6, 20, 0, tzinfo=IST)) == ""
    finally:
        await close_world(w)


async def test_sync_does_not_run_without_the_google_switch(world: World):
    out = await world.consumer.periodic()
    assert "calendar_sync" not in out


async def test_the_clash_note_reaches_the_booking_offer_text(world: World):
    """The task engine's offer text asks the consumer component; the note is appended."""
    await world.say("kal 6 baje dentist hai")
    engine = world.c.get("task_engine")
    from types import SimpleNamespace

    summary = SimpleNamespace(appointment_at=datetime(2026, 1, 6, 18, 20, tzinfo=IST))
    note = await engine._clash_note(
        SimpleNamespace(requester_user_id=world.user.id, id="t1"), summary, SimpleNamespace()
    )
    assert note.startswith("\n") and "appointment" in note.lower()
    none = await engine._clash_note(
        SimpleNamespace(requester_user_id=world.user.id, id="t1"),
        SimpleNamespace(appointment_at=datetime(2026, 1, 6, 9, 0, tzinfo=IST)),
        SimpleNamespace(),
    )
    assert none == ""
