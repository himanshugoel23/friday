"""CalendarClient: CRUD, idempotency, clash detection, timezone edges, token handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from friday.google import scopes as sc
from friday.google.calendar import (
    DEFAULT_TZ,
    CalendarClient,
    CalendarError,
    InvalidTimeRange,
    event_id_for,
)
from friday.google.oauth import NeedsReconnect, ScopeMissing
from tests.google.conftest import connect_user

IST = DEFAULT_TZ


def at(h: int, m: int = 0, day: int = 6) -> datetime:
    return datetime(2026, 1, day, h, m, tzinfo=IST)


@pytest.fixture
async def cal(oauth, fake, alice, gsettings):
    await connect_user(oauth, fake, alice.id)
    return CalendarClient(oauth, alice.id, settings=gsettings, http=fake.client_factory())


def test_default_zone_is_kolkata():
    assert DEFAULT_TZ.key == "Asia/Kolkata"


async def test_create_list_delete(cal):
    ev = await cal.create_event("Dentist", at(10), at(11), idempotency_key="k1", location="Clinic")
    assert ev.summary == "Dentist" and ev.start == at(10) and ev.end == at(11)
    assert ev.start.tzinfo is not None and ev.location == "Clinic"
    got = await cal.list_events(at(0), at(23, 59))
    assert [e.id for e in got] == [ev.id]
    assert await cal.delete_event(ev.id) is True
    assert await cal.list_events(at(0), at(23, 59)) == []
    assert await cal.delete_event(ev.id) is False  # already gone: idempotent
    assert await cal.delete_event("fri-unknown") is False


async def test_create_is_idempotent(cal, fake):
    a = await cal.create_event("Salon", at(15), at(16), idempotency_key="task-9:booking")
    b = await cal.create_event("Salon", at(15), at(16), idempotency_key="task-9:booking")
    assert a.id == b.id
    assert len(await cal.list_events(at(0), at(23, 59))) == 1
    c = await cal.create_event("Salon", at(15), at(16), idempotency_key="task-10:booking")
    assert c.id != a.id and len(await cal.list_events(at(0), at(23, 59))) == 2


async def test_idempotency_key_is_private_property_hash_not_plain(cal, fake):
    await cal.create_event("X", at(9), at(10), idempotency_key="secret-looking-key")
    stored = next(iter(fake.events["sub-alice"].values()))
    assert "secret-looking-key" not in str(stored)
    assert stored["extendedProperties"]["private"]["friday_key"]


async def test_event_id_is_valid_google_id_and_per_user():
    eid = event_id_for("u1", "k")
    assert 5 <= len(eid) <= 1024 and set(eid) <= set("0123456789abcdefghijklmnopqrstuv")
    assert event_id_for("u1", "k") == eid and event_id_for("u2", "k") != eid


async def test_recreate_after_delete_restores_event(cal):
    ev = await cal.create_event("Gym", at(7), at(8), idempotency_key="g")
    await cal.delete_event(ev.id)
    again = await cal.create_event("Gym", at(7), at(8), idempotency_key="g")
    assert again.id == ev.id
    assert len(await cal.list_events(at(0), at(23, 59))) == 1


# ------------------------------------------------------------------ clashes
async def test_clash_detection_basics(cal):
    await cal.create_event("Meeting", at(10), at(11), idempotency_key="m")
    assert [e.summary for e in await cal.clashes(at(10, 30), at(11, 30))] == ["Meeting"]
    assert [e.summary for e in await cal.clashes(at(9, 30), at(10, 30))] == ["Meeting"]
    assert [e.summary for e in await cal.clashes(at(9), at(12))] == ["Meeting"]  # contains it
    assert [e.summary for e in await cal.clashes(at(10, 15), at(10, 45))] == ["Meeting"]  # inside
    assert await cal.clashes(at(11), at(12)) == []  # touching end is free
    assert await cal.clashes(at(9), at(10)) == []  # touching start is free
    assert await cal.clashes(at(13), at(14)) == []


async def test_clash_ignores_free_and_cancelled(cal, fake):
    ev = await cal.create_event("FYI", at(10), at(11), idempotency_key="f")
    fake.events["sub-alice"][ev.id]["transparency"] = "transparent"
    assert await cal.clashes(at(10), at(11)) == []
    gone = await cal.create_event("Gone", at(14), at(15), idempotency_key="g")
    await cal.delete_event(gone.id)
    assert await cal.clashes(at(14), at(15)) == []


async def test_clash_utc_input_same_instant(cal):
    """18:30 UTC is 00:00 IST the next day: an event 23:30-00:30 IST clashes with it."""
    await cal.create_event("Late call", at(23, 30, day=6), at(0, 30, day=7), idempotency_key="l")
    utc = datetime(2026, 1, 6, 18, 30, tzinfo=UTC)
    assert [e.summary for e in await cal.clashes(utc, utc + timedelta(minutes=15))] == ["Late call"]
    assert await cal.clashes(utc + timedelta(hours=1), utc + timedelta(hours=2)) == []


async def test_clash_across_midnight_ist(cal):
    await cal.create_event("Night train", at(22), at(6, day=7), idempotency_key="t")
    assert len(await cal.clashes(at(23, 50), at(0, 10, day=7))) == 1
    assert await cal.clashes(at(6, 30, day=7), at(7, day=7)) == []


async def test_clash_naive_input_is_read_as_kolkata(cal):
    await cal.create_event("Call", at(10), at(11), idempotency_key="n")
    naive = datetime(2026, 1, 6, 10, 30)
    assert len(await cal.clashes(naive, naive + timedelta(minutes=30))) == 1
    # the same wall clock in New York is a different instant: no clash
    ny = datetime(2026, 1, 6, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    assert await cal.clashes(ny, ny + timedelta(minutes=30)) == []


async def test_event_in_other_timezone_compared_by_instant(cal, fake):
    """An event stored in London time (05:00 UTC = 10:30 IST) clashes with 10:30 IST."""
    ev = await cal.create_event("London", at(1), at(2), idempotency_key="ld")
    fake.events["sub-alice"][ev.id]["start"] = {"dateTime": "2026-01-06T05:00:00+00:00"}
    fake.events["sub-alice"][ev.id]["end"] = {"dateTime": "2026-01-06T06:00:00+00:00"}
    assert len(await cal.clashes(at(10, 30), at(11))) == 1
    got = (await cal.list_events(at(0), at(23, 59)))[0]
    assert got.start == at(10, 30) and got.start.utcoffset() == timedelta(hours=5, minutes=30)


async def test_all_day_event_uses_kolkata_midnight(cal, fake):
    fake.events.setdefault("sub-alice", {})["ad"] = {
        "id": "ad", "status": "confirmed", "summary": "Holiday",
        "start": {"date": "2026-01-06"}, "end": {"date": "2026-01-07"},
    }  # fmt: skip
    got = (await cal.list_events(at(0), at(23, 59)))[0]
    assert got.all_day and got.start == at(0) and got.end == at(0, day=7)
    assert len(await cal.clashes(at(0), at(0, 5))) == 1
    assert await cal.clashes(at(23, 59, day=5), at(0, day=6)) == []


async def test_invalid_ranges(cal):
    with pytest.raises(InvalidTimeRange):
        await cal.clashes(at(11), at(10))
    with pytest.raises(InvalidTimeRange):
        await cal.create_event("x", at(10), at(10), idempotency_key="z")
    with pytest.raises(InvalidTimeRange):
        await cal.find_free_slots(at(9), at(17), timedelta(0))


# ------------------------------------------------------------------ free slots
async def test_find_free_slots(cal):
    await cal.create_event("A", at(10), at(11), idempotency_key="a")
    await cal.create_event("B", at(11), at(12), idempotency_key="b")  # back to back
    await cal.create_event("C", at(15), at(16), idempotency_key="c")
    slots = await cal.find_free_slots(at(9), at(17), timedelta(minutes=60))
    got = [(s.start, s.end) for s in slots]
    assert got == [(at(9), at(10)), (at(12), at(15)), (at(16), at(17))]
    short = await cal.find_free_slots(at(9), at(17), timedelta(hours=3))
    assert [(s.start, s.end) for s in short] == [(at(12), at(15))]
    assert await cal.find_free_slots(at(9), at(17), timedelta(hours=4)) == []
    assert len(await cal.find_free_slots(at(9), at(17), timedelta(minutes=30), limit=2)) == 2


async def test_free_slots_event_spanning_window_edges(cal):
    await cal.create_event("Long", at(8), at(10), idempotency_key="long")
    slots = await cal.find_free_slots(at(9), at(12), timedelta(minutes=30))
    assert [(s.start, s.end) for s in slots] == [(at(10), at(12))]


async def test_list_events_paginates(cal, fake):
    fake.page_size = 2
    for i in range(5):
        await cal.create_event(f"E{i}", at(8 + i), at(9 + i), idempotency_key=f"p{i}")
    got = await cal.list_events(at(0), at(23, 59))
    assert [e.summary for e in got] == [f"E{i}" for i in range(5)]


# ------------------------------------------------------------------ tokens and errors
async def test_expired_access_token_refreshes_and_retries(cal, fake):
    before = len([r for r in fake.requests if "grant_type=refresh_token" in r["body"]])
    fake.expire_access_tokens()  # Google says 401 although our clock thinks it is valid
    await cal.create_event("After expiry", at(9), at(10), idempotency_key="e")
    after = len([r for r in fake.requests if "grant_type=refresh_token" in r["body"]])
    assert after == before + 1
    assert len(await cal.list_events(at(0), at(23, 59))) == 1


async def test_refresh_failure_surfaces_needs_reconnect(cal, fake, oauth, alice):
    fake.expire_access_tokens()
    fake.fail_refresh = True
    with pytest.raises(NeedsReconnect):
        await cal.list_events(at(0), at(23))
    assert (await oauth.status(alice.id)).status == "needs_reconnect"


async def test_calendar_scope_required(oauth, fake, alice, gsettings):
    fake.grant_override = [sc.OPENID, sc.EMAIL, sc.CALENDAR_EVENTS]
    await connect_user(oauth, fake, alice.id)
    conn = await oauth.repo.get(alice.id)
    conn.scopes = [sc.OPENID, sc.EMAIL]
    await oauth.repo.upsert(conn)
    client = CalendarClient(oauth, alice.id, settings=gsettings, http=fake.client_factory())
    with pytest.raises(ScopeMissing):
        await client.list_events(at(0), at(23))


async def test_http_error_becomes_calendar_error(cal, fake):
    ev = await cal.create_event("x", at(9), at(10), idempotency_key="x")
    fake.events["sub-alice"].pop(ev.id)
    with pytest.raises(CalendarError) as e:
        await cal._request("GET", f"/calendars/primary/events/{ev.id}")
    assert e.value.code == "http_404"


async def test_users_calendars_are_separate(oauth, fake, alice, bob, gsettings):
    await connect_user(oauth, fake, alice.id, "alice")
    await connect_user(oauth, fake, bob.id, "bob")
    ca = CalendarClient(oauth, alice.id, settings=gsettings, http=fake.client_factory())
    cb = CalendarClient(oauth, bob.id, settings=gsettings, http=fake.client_factory())
    await ca.create_event("Alice only", at(9), at(10), idempotency_key="same-key")
    assert await cb.list_events(at(0), at(23)) == []
    b = await cb.create_event("Bob only", at(9), at(10), idempotency_key="same-key")
    assert b.summary == "Bob only"  # same key, different user: different event


async def test_requests_carry_bearer_and_no_other_scopes(cal, fake):
    await cal.list_events(at(0), at(23))
    last = [r for r in fake.requests if r["path"].startswith("/calendar")][-1]
    assert last["auth"].startswith("Bearer ya29.")
