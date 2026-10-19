"""Export, delete everything, encryption at rest, no cross-user leakage, schema files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from friday.core.clock import IST
from friday.lifestate import copy
from friday.lifestate.models import (
    EventKind,
    Followup,
    LifeCommitment,
    LifeEvent,
    PersonRef,
    Repeat,
)
from friday.lifestate.store import MemoryLifeStore, delete_everything, export_life_state

SECRET_TITLE = "Interview at Zephyr Corp salary 40 lakh"
SECRET_NOTE = "they asked about my layoffs"
SECRET_PLACE = "Zephyr Tower Sector 62"
SECRET_COMMIT = "mummy ki insulin"
SECRET_PERSON = "Sunita Devi"


def t(h: int, day: int = 20) -> datetime:
    return datetime(2026, 10, day, h, 0, tzinfo=IST)


async def fill(store, uid):
    e = LifeEvent(
        user_id=uid,
        title=SECRET_TITLE,
        start=t(14),
        end=t(15),
        kind=EventKind.INTERVIEW,
        protected=True,
        location=SECRET_PLACE,
        note=SECRET_NOTE,
        source_ref="g1",
    )
    await store.save_event(e)
    c = LifeCommitment(
        user_id=uid,
        text=SECRET_COMMIT,
        due=t(8),
        repeat=Repeat(freq="daily", time="08:00"),
        person=PersonRef(name=SECRET_PERSON, relationship="mother"),
    )
    await store.save_commitment(c)
    await store.set_topic(uid, "after_event", muted=True)
    await store.set_topic(uid, "bill_due", channel="voice_note")
    await store.save_followup(
        Followup(
            user_id=uid,
            key="k1",
            topic="after_event:interview",
            status="sent",
            text="Interview kaisa gaya? " + SECRET_TITLE,
            due_at=t(12),
            sent_at=t(12),
            created_at=t(12),
        )
    )
    return e, c


async def test_roundtrip_of_every_field(world):
    e, c = await fill(world.store, world.u1)
    got = await world.store.get_event(world.u1, e.id)
    assert got.title == SECRET_TITLE and got.location == SECRET_PLACE and got.note == SECRET_NOTE
    assert got.protected and got.kind == EventKind.INTERVIEW and got.start == t(14)
    assert got.start.tzinfo is not None
    gc = await world.store.get_commitment(world.u1, c.id)
    assert gc.text == SECRET_COMMIT and gc.person.name == SECRET_PERSON
    assert gc.repeat.freq == "daily" and gc.repeat.time == "08:00"
    prefs = {p.topic: p for p in await world.store.list_topics(world.u1)}
    assert prefs["after_event"].muted and prefs["bill_due"].channel == "voice_note"
    fu = await world.store.get_followup(world.u1, "k1")
    assert SECRET_TITLE in fu.text


async def test_events_between_boundaries(world):
    e = LifeEvent(user_id=world.u1, title="x", start=t(14), end=t(15), kind=EventKind.MEETING)
    await world.store.save_event(e)
    assert await world.store.events_between(world.u1, t(15), t(16)) == []  # ends exactly at start
    assert (
        len(
            await world.store.events_between(
                world.u1,
                t(13),
                t(
                    14,
                ),
            )
        )
        == 0
    )  # starts at window end
    assert len(await world.store.events_between(world.u1, t(14), t(15))) == 1


async def test_export_is_complete_json_and_only_for_that_user(world):
    await fill(world.store, world.u1)
    await world.store.save_event(
        LifeEvent(user_id=world.u2, title="other person's thing", start=t(9), end=t(10))
    )
    data = await export_life_state(world.store, world.u1)
    blob = json.dumps(data)  # must be JSON-serialisable
    assert SECRET_TITLE in blob and SECRET_NOTE in blob and SECRET_COMMIT in blob
    assert "other person" not in blob
    assert data["format"] == "friday-life-state-v1" and data["user_id"] == world.u1
    assert len(data["events"]) == 1 and len(data["commitments"]) == 1
    assert {p["topic"] for p in data["topic_preferences"]} == {"after_event", "bill_due"}
    assert len(data["messages_sent"]) == 1


async def test_delete_everything_removes_all_and_only_that_users_rows(world):
    await fill(world.store, world.u1)
    await fill(world.store, world.u2)
    counts = await delete_everything(world.store, world.u1)
    assert counts == {
        "life_followups": 1,
        "mute_topics": 2,
        "life_commitments": 1,
        "life_events": 1,
    }
    assert await world.store.list_events(world.u1) == []
    assert await world.store.list_commitments(world.u1) == []
    assert await world.store.list_topics(world.u1) == []
    assert await world.store.list_followups(world.u1) == []
    assert len(await world.store.list_events(world.u2)) == 1  # untouched
    assert len(await world.store.list_commitments(world.u2)) == 1


async def test_no_cross_user_reads_or_writes(world):
    e, c = await fill(world.store, world.u1)
    assert await world.store.get_event(world.u2, e.id) is None
    assert await world.store.get_commitment(world.u2, c.id) is None
    assert await world.store.find_event_by_ref(world.u2, "user", "g1") is None
    assert await world.store.events_between(world.u2, t(0), t(23)) == []
    assert await world.store.list_followups(world.u2) == []
    assert await world.store.get_followup(world.u2, "k1") is None
    assert not await world.store.delete_event(world.u2, e.id)
    assert not await world.store.delete_commitment(world.u2, c.id)
    # u2 cannot overwrite u1's row by reusing its id
    hijack = e.model_copy(update={"user_id": world.u2, "title": "hijacked"})
    with pytest.raises(PermissionError):
        await world.store.save_event(hijack)
    assert (await world.store.get_event(world.u1, e.id)).title == SECRET_TITLE
    # mute is per user
    assert await world.store.list_topics(world.u2) == []


async def test_encrypted_at_rest(world):
    if world.kind != "sql":
        pytest.skip("encryption is a property of the SQL columns")
    await fill(world.store, world.u1)
    async with world.container.db.session() as s:
        ev_row = (await s.execute(text("select title, location, note from life_events"))).one()
        co_row = (await s.execute(text("select text, person from life_commitments"))).one()
        fu_row = (await s.execute(text("select text from life_followups"))).one()
    for value, plain in (
        (ev_row[0], SECRET_TITLE),
        (ev_row[1], SECRET_PLACE),
        (ev_row[2], SECRET_NOTE),
        (co_row[0], SECRET_COMMIT),
        (co_row[1], SECRET_PERSON),
        (fu_row[0], SECRET_TITLE),
    ):
        assert value.startswith("v1:"), "not ciphertext"
        assert plain not in value


async def test_erasure_through_the_account_purger(world):
    if world.kind != "sql":
        pytest.skip("purger works on the database")
    await fill(world.store, world.u1)
    await fill(world.store, world.u2)
    await world.container.repos.purger.purge_user(world.u1)
    async with world.container.db.session() as s:
        for table in ("life_events", "life_commitments", "mute_topics", "life_followups"):
            n1 = (
                await s.execute(
                    text(f"select count(*) from {table} where user_id = :u"), {"u": world.u1}
                )
            ).scalar()
            n2 = (
                await s.execute(
                    text(f"select count(*) from {table} where user_id = :u"), {"u": world.u2}
                )
            ).scalar()
            assert n1 == 0 and n2 >= 1


async def test_memory_store_hides_stored_objects_from_callers():
    s = MemoryLifeStore()
    e = LifeEvent(user_id="a", title="x", start=t(9), end=t(10))
    await s.save_event(e)
    got = await s.get_event("a", e.id)
    got.title = "mutated"
    assert (await s.get_event("a", e.id)).title == "x"


def test_schema_and_rls_files_cover_the_new_tables():
    root = Path(__file__).resolve().parents[2] / "deploy" / "supabase"
    schema, rls = (root / "schema.sql").read_text(), (root / "rls.sql").read_text()
    for table in ("life_events", "life_commitments", "mute_topics", "life_followups"):
        assert f"CREATE TABLE {table}" in schema
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;" in rls


def test_copy_is_marked_pending_founder_approval():
    assert copy.PENDING_FOUNDER_APPROVAL is True
    assert "PENDING_FOUNDER_APPROVAL" in (copy.__doc__ or "")
