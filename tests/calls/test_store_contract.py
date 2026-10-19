"""The same contract for the in-memory stores and the database repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from friday.calls.contacts import Contact, MemoryContactStore
from friday.calls.dnc import DncEntry, MemoryDncStore
from friday.calls.models import (
    CallBrief,
    CalleeKind,
    CallOutcome,
    CallRequest,
    CallStatus,
    OutcomeStatus,
)
from friday.calls.numbers import NumberHasher
from friday.calls.stores import AttemptRecord, MemoryCallStore
from friday.core.clock import IST, FakeClock
from friday.core.models import User, UserStatus
from friday.db.repositories.consumer_calls import (
    CallDncRepo,
    ConsumerCallsRepo,
    ConsumerContactsRepo,
)
from friday.db.repositories.users import UserRepo
from tests.calls.conftest import MUMMY

NOW = datetime(2026, 1, 5, 11, 0, tzinfo=IST)


@dataclass
class Stores:
    calls: object
    contacts: object
    dnc: object
    u1: str
    u2: str
    kind: str


@pytest.fixture(params=["memory", "db"])
async def stores(request, db):
    clock = FakeClock(NOW)
    if request.param == "memory":
        return Stores(
            MemoryCallStore(), MemoryContactStore(), MemoryDncStore(), "user-1", "user-2", "memory"
        )
    users = UserRepo(db, clock)
    a = await users.add(User(phone="+919800000011", status=UserStatus.ACTIVE))
    b = await users.add(User(phone="+919800000012", status=UserStatus.ACTIVE))
    return Stores(
        ConsumerCallsRepo(db, clock),
        ConsumerContactsRepo(db, clock),
        CallDncRepo(db, clock),
        a.id,
        b.id,
        "db",
    )


def req(user: str, **kw) -> CallRequest:
    base = dict(
        user_id=user, callee_kind=CalleeKind.FAMILY_FRIEND, purpose="main late hoon",
        callee_name="Mummy", callee_number=MUMMY, source_message_id="wamid.1", created_at=NOW,
        updated_at=NOW, group_members=["a", "b"],
    )  # fmt: skip
    return CallRequest(**{**base, **kw})


async def test_request_round_trip_and_idempotent_create(stores):
    r = req(stores.u1)
    stored, created = await stores.calls.create_request(r)
    assert created and stored.id == r.id
    again, created2 = await stores.calls.create_request(req(stores.u1))  # new object, same message
    assert not created2 and again.id == r.id
    got = await stores.calls.get_request(r.id)
    assert got.purpose == "main late hoon" and got.callee_number == MUMMY
    assert got.group_members == ["a", "b"] and got.callee_kind == CalleeKind.FAMILY_FRIEND
    assert await stores.calls.get_request("nope") is None
    other, c3 = await stores.calls.create_request(req(stores.u1, source_message_id="wamid.2"))
    assert c3 and other.id != r.id


async def test_save_children_due_and_listing(stores):
    p = req(stores.u1, callee_kind=CalleeKind.GROUP, source_message_id="g")
    await stores.calls.create_request(p)
    kids = []
    for i in range(2):
        k = req(stores.u1, parent_id=p.id, source_message_id=f"g:{i}", callee_name=f"K{i}")
        await stores.calls.create_request(k)
        kids.append(k)
    assert {c.id for c in await stores.calls.children(p.id)} == {k.id for k in kids}
    k0 = kids[0]
    k0.status, k0.next_attempt_at, k0.attempts = CallStatus.SCHEDULED, NOW, 1
    k0.updated_at = NOW + timedelta(minutes=1)
    await stores.calls.save_request(k0)
    assert [r.id for r in await stores.calls.due(NOW)] == [k0.id]
    assert await stores.calls.due(NOW - timedelta(minutes=1)) == []
    assert len(await stores.calls.list_for_user(stores.u1)) == 3
    assert await stores.calls.list_for_user(stores.u2) == []
    k0.status, k0.updated_at = CallStatus.CALLING, NOW - timedelta(hours=2)
    await stores.calls.save_request(k0)
    assert [r.id for r in await stores.calls.stale_calling(NOW - timedelta(hours=1))] == [k0.id]
    assert await stores.calls.stale_calling(NOW - timedelta(hours=3)) == []


async def test_brief_round_trip_keeps_the_approval(stores):
    r = req(stores.u1)
    await stores.calls.create_request(r)
    b = CallBrief(
        request_id=r.id, user_id=stores.u1, callee_kind=CalleeKind.FAMILY_FRIEND, goal="late",
        private_facts=["secret"], must_say=["late hoon"],
    )  # fmt: skip
    b = b.model_copy(
        update={"approved": True, "approval_hash": b.content_hash(), "approved_at": NOW}
    )
    await stores.calls.save_brief(b)
    got = await stores.calls.get_brief(r.id)
    assert got == b and got.is_approved_as_is() and got.private_facts == ["secret"]
    edited = got.model_copy(update={"goal": "changed", "approved": False, "approval_hash": None})
    await stores.calls.save_brief(edited)  # replaces, one current brief per request
    assert (await stores.calls.get_brief(r.id)).goal == "changed"
    assert await stores.calls.get_brief("nope") is None


async def test_outcomes_attempts_counters_and_strikes(stores):
    r = req(stores.u1)
    await stores.calls.create_request(r)
    o = CallOutcome(
        request_id=r.id, attempt=1, status=OutcomeStatus.COMPLETED, summary="ok", started_at=NOW,
        duration_s=30, recording_ref="s3://b/x.wav",
    )  # fmt: skip
    await stores.calls.add_outcome(stores.u1, o, "H1")
    (got,) = await stores.calls.outcomes(r.id)
    assert got.summary == "ok" and got.recording_ref == "s3://b/x.wav"

    day = (NOW.replace(hour=0), NOW.replace(hour=0) + timedelta(days=1))
    for uid, h, mins in ((stores.u1, "H1", 0), (stores.u1, "H1", 5), (stores.u2, "H1", 10)):
        await stores.calls.record_attempt(
            AttemptRecord(uid, r.id, h, NOW + timedelta(minutes=mins), 60)
        )
    assert await stores.calls.calls_between(stores.u1, *day) == 2
    assert await stores.calls.seconds_between(stores.u1, *day) == 120
    assert await stores.calls.calls_between(stores.u2, *day) == 1
    assert await stores.calls.number_calls_since("H1", NOW - timedelta(days=1)) == 3  # all users
    assert await stores.calls.number_calls_since("H1", NOW + timedelta(minutes=6)) == 1
    assert await stores.calls.number_calls_since("other", NOW - timedelta(days=1)) == 0

    assert await stores.calls.strikes(stores.u1) == 0
    assert await stores.calls.add_strike(stores.u1, "threat", NOW) == 1
    assert await stores.calls.add_strike(stores.u1, "scam", NOW) == 2
    assert await stores.calls.strikes(stores.u2) == 0


async def test_recordings_are_per_user(stores):
    r1, r2 = req(stores.u1), req(stores.u2, source_message_id="x")
    await stores.calls.create_request(r1)
    await stores.calls.create_request(r2)
    for r, uid, ref, age in ((r1, stores.u1, "s3://b/1", 40), (r2, stores.u2, "s3://b/2", 1)):
        await stores.calls.add_outcome(
            uid,
            CallOutcome(
                request_id=r.id,
                status=OutcomeStatus.COMPLETED,
                recording_ref=ref,
                started_at=NOW - timedelta(days=age),
            ),  # fmt: skip
            "H",
        )
    assert [x.ref for x in await stores.calls.recordings(stores.u1)] == ["s3://b/1"]
    assert [x.ref for x in await stores.calls.recordings_before(NOW - timedelta(days=30))] == [
        "s3://b/1"
    ]
    assert not await stores.calls.clear_recording(stores.u2, "s3://b/1")  # not theirs
    assert await stores.calls.clear_recording(stores.u1, "s3://b/1")
    assert await stores.calls.recordings(stores.u1) == []
    assert len(await stores.calls.recordings(stores.u2)) == 1


async def test_contacts_are_per_user(stores):
    h = NumberHasher().hash if stores.kind == "db" else NumberHasher(None).hash
    del h  # hashing is the caller's job; the store only keeps what it is given
    c = Contact(user_id=stores.u1, name="Mummy", number=MUMMY, number_hash="HH",
                nicknames=["mummy"], relationship="mother")  # fmt: skip
    await stores.contacts.save(c)
    got = await stores.contacts.get(stores.u1, c.id)
    assert got.name == "Mummy" and got.number == MUMMY and got.nicknames == ["mummy"]
    assert got.relationship == "mother" and not got.confirmed
    assert await stores.contacts.get(stores.u2, c.id) is None
    assert await stores.contacts.find_by_hash(stores.u2, "HH") is None
    assert (await stores.contacts.find_by_hash(stores.u1, "HH")).id == c.id
    c.confirmed_at = NOW
    await stores.contacts.save(c)
    assert (await stores.contacts.get(stores.u1, c.id)).confirmed
    assert [x.id for x in await stores.contacts.list_for_user(stores.u1)] == [c.id]
    assert await stores.contacts.list_for_user(stores.u2) == []
    assert not await stores.contacts.delete(stores.u2, c.id)
    assert await stores.contacts.delete(stores.u1, c.id)


async def test_dnc_store(stores):
    e = DncEntry("abc" * 21 + "d", "opt_out_call", "req:1", NOW)
    assert await stores.dnc.add(e) and not await stores.dnc.add(e)
    got = await stores.dnc.get(e.number_hash)
    assert got.reason == "opt_out_call" and got.source == "req:1"
    assert await stores.dnc.count() == 1
    assert await stores.dnc.get("zzz") is None
    assert await stores.dnc.delete(e.number_hash) and not await stores.dnc.delete(e.number_hash)


# ------------------------------------------------------------------ database specifics


async def test_numbers_and_text_are_encrypted_at_rest(db):
    clock = FakeClock(NOW)
    u = await UserRepo(db, clock).add(User(phone="+919800000013", status=UserStatus.ACTIVE))
    calls, contacts = ConsumerCallsRepo(db, clock), ConsumerContactsRepo(db, clock)
    r = req(u.id, raw_text="mummy ko bata do ki main late hoon")
    await calls.create_request(r)
    await calls.save_brief(
        CallBrief(
            request_id=r.id,
            user_id=u.id,
            callee_kind=CalleeKind.FAMILY_FRIEND,
            goal="g",
            private_facts=["meri FD"],
        )  # fmt: skip
    )
    await contacts.save(Contact(user_id=u.id, name="Mummy Goel", number=MUMMY, number_hash="HH"))
    async with db.session() as s:
        rows = [
            ("call_requests", "callee_number"), ("call_requests", "purpose"),
            ("call_requests", "raw_text"), ("call_briefs", "payload"),
            ("consumer_contacts", "number"), ("consumer_contacts", "name"),
        ]  # fmt: skip
        for table, col in rows:
            raw = (await s.execute(text(f"select {col} from {table}"))).scalar_one()
            assert raw.startswith("v1:"), (table, col)
            assert "9000000001" not in raw and "Goel" not in raw
        dump = ""
        for t in ("call_dnc", "call_attempts", "call_strikes"):
            for row in (await s.execute(text(f"select * from {t}"))).all():
                dump += " ".join(str(v) for v in row)
        assert "9000000001" not in dump


async def test_dnc_table_has_no_number_and_no_user_column(db):
    async with db.session() as s:
        cols = {r[1] for r in (await s.execute(text("pragma table_info(call_dnc)"))).all()}
    assert cols == {"id", "number_hash", "reason", "source", "created_at"}


async def test_erasure_removes_user_data_but_keeps_the_dnc_entry(db):
    from friday.db.repositories.purge import DataPurger

    clock = FakeClock(NOW)
    u = await UserRepo(db, clock).add(User(phone="+919800000014", status=UserStatus.ACTIVE))
    calls, contacts, dnc = (
        ConsumerCallsRepo(db, clock), ConsumerContactsRepo(db, clock), CallDncRepo(db, clock),
    )  # fmt: skip
    r = req(u.id)
    await calls.create_request(r)
    await calls.save_brief(
        CallBrief(request_id=r.id, user_id=u.id, callee_kind=CalleeKind.FAMILY_FRIEND, goal="g")
    )
    await calls.add_outcome(
        u.id,
        CallOutcome(request_id=r.id, status=OutcomeStatus.OPTED_OUT, recording_ref="s3://b/rec"),
        "H",
    )
    await calls.record_attempt(AttemptRecord(u.id, r.id, "H", NOW, 5))
    await calls.add_strike(u.id, "prank", NOW)
    await contacts.save(Contact(user_id=u.id, name="Mummy", number=MUMMY, number_hash="HH"))
    await dnc.add(DncEntry("f" * 64, "opt_out_call", "req:x", NOW))

    purger = DataPurger(db, clock)
    assert await purger.recording_urls(u.id) == ["s3://b/rec"]  # collected BEFORE the purge
    counts = await purger.purge_user(u.id)
    assert counts["call_requests"] == 1 and counts["consumer_contacts"] == 1
    assert await calls.get_request(r.id) is None and await calls.get_brief(r.id) is None
    assert await calls.outcomes(r.id) == [] and await calls.strikes(u.id) == 0
    assert await contacts.list_for_user(u.id) == []
    assert await dnc.count() == 1  # the recipient's protection survives the user's erasure


async def test_registered_in_the_repository_bundle(container):
    r = container.repos
    assert r.consumer_calls and r.consumer_contacts and r.call_dnc
