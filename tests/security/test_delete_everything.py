"""Red team: DPDP right to erasure. After "delete everything" a raw dump of every
table must contain none of the user's personal data; other users are untouched."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from friday.core.models import (
    AccountIdentifier,
    CallOutcome,
    CallResult,
    DialStatus,
    Fact,
    FactKind,
    Intent,
    Interpretation,
    MidCallQuestion,
    Person,
    PersonConsent,
    Place,
    Speaker,
    Task,
    TaskSpec,
    TaskStatus,
    TaskType,
    Transcript,
    UserStatus,
)
from tests.security.conftest import (
    ACCOUNT_NO,
    ALICE_PHONE,
    BOB_PHONE,
    DAD_NOTES,
    DAD_PHONE,
    HOME_ADDRESS,
    PIN,
    make_active_user,
    say,
)

SECRET_PHRASE = "my landlord Mr Kapoor owes me 40k"
TRANSCRIPT_LINE = "Patient Ramesh ji ka sugar 280 hai"


async def _dump_all(db) -> str:
    import friday.db.tables  # noqa: F401
    from friday.db.base import Base

    out = []
    async with db.engine.connect() as conn:
        for table in Base.metadata.tables:
            rows = (await conn.execute(text(f"SELECT * FROM {table}"))).all()  # noqa: S608
            out += [f"{table}: {tuple(r)!r}" for r in rows]
    return "\n".join(out)


async def _seed(repos, clock, user, recording_url: str | None = None) -> Task:
    await repos.people.upsert(
        Person(owner_user_id=user.id, name="Ramesh Verma", relation="father", phone=DAD_PHONE,
               notes=DAD_NOTES, contact_consent=PersonConsent.OPTED_IN)
    )
    await repos.places.upsert(Place(owner_user_id=user.id, label="Home", address_text=HOME_ADDRESS))
    await repos.identifiers.upsert(
        AccountIdentifier(user_id=user.id, company="Airtel", label="Account number",
                          value=ACCOUNT_NO)
    )
    await repos.facts.upsert(
        Fact(user_id=user.id, kind=FactKind.GENERAL, key="landlord", value=SECRET_PHRASE)
    )
    task = Task(
        requester_user_id=user.id,
        type=TaskType.HEALTHCARE,
        status=TaskStatus.COMPLETED,
        spec=TaskSpec(type=TaskType.HEALTHCARE, goal="Book a diabetologist for Ramesh Verma",
                      business_phone="+918040000001"),
    )
    await repos.tasks.add(task)
    tr = Transcript()
    tr.add(Speaker.CALLEE, TRANSCRIPT_LINE)
    await repos.tasks.save_call(
        CallResult(task_id=task.id, provider="simulator", to_phone="+918040000001",
                   dial_status=DialStatus.ANSWERED, outcome=CallOutcome.SUCCESS, transcript=tr,
                   recording_url=recording_url)
    )
    await repos.tasks.add_question(
        MidCallQuestion(task_id=task.id, text="Ramesh ji ke liye 5pm theek hai?")
    )
    await repos.audit.log("task.note", user_id=user.id, note="Ramesh Verma diabetic")
    return task


async def _delete_via_chat(pipeline, channel, fake_brain) -> list[str]:
    fake_brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    replies = await say(pipeline, channel, ALICE_PHONE, "delete everything")
    replies += await say(pipeline, channel, ALICE_PHONE, PIN)
    replies += await say(pipeline, channel, ALICE_PHONE, "DELETE")
    return replies


PII_MARKERS = [
    "Rahul Verma",  # profile name
    "Ramesh",  # circle member
    "insulin",  # health note
    "Shanti Apartments",  # address
    ACCOUNT_NO,
    SECRET_PHRASE,
    "sugar 280",  # transcript
    ALICE_PHONE,
    DAD_PHONE,
]


async def test_delete_everything_leaves_no_pii(repos, clock, db, pipeline, channel,
                                               fake_brain) -> None:
    alice = await make_active_user(repos, clock, ALICE_PHONE)
    await _seed(repos, clock, alice)
    await say(pipeline, channel, ALICE_PHONE, f"remember: {SECRET_PHRASE}")
    bob = await make_active_user(repos, clock, BOB_PHONE, name="Bob Bhai")
    await repos.facts.upsert(Fact(user_id=bob.id, kind=FactKind.GENERAL, key="k", value="bob-ok"))

    await _delete_via_chat(pipeline, channel, fake_brain)

    dump = await _dump_all(db)
    leaked = [ln for ln in dump.splitlines() if any(m in ln for m in PII_MARKERS)]
    assert leaked == []
    tomb = await repos.users.get(alice.id)
    assert tomb.status == UserStatus.DELETED and tomb.pin_hash is None
    assert await repos.users.get_by_phone(ALICE_PHONE) is None
    assert [f.value for f in await repos.facts.list_for_user(bob.id)] == ["bob-ok"]
    assert any(e.action == "data.deleted" for e in await repos.audit.list_for_user(alice.id))


async def test_delete_requires_pin_and_confirmation(repos, clock, pipeline, channel,
                                                    fake_brain) -> None:
    alice = await make_active_user(repos, clock, ALICE_PHONE)
    await _seed(repos, clock, alice)
    fake_brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    await say(pipeline, channel, ALICE_PHONE, "delete everything")
    await say(pipeline, channel, ALICE_PHONE, "7391")  # wrong PIN
    await say(pipeline, channel, ALICE_PHONE, "DELETE")
    assert (await repos.users.get(alice.id)).status == UserStatus.ACTIVE
    assert await repos.people.list_for_owner(alice.id)


@pytest.mark.xfail(
    strict=True,
    reason="SECURITY-14: purge deletes DB rows but not call recordings (local files / "
    "telephony provider storage)",
)
async def test_delete_everything_removes_recordings(repos, clock, pipeline, channel, fake_brain,
                                                    tmp_path) -> None:
    rec = Path(tmp_path) / "rec-alice.wav"
    rec.write_bytes(b"RIFF....fake audio of Ramesh's health discussion")
    alice = await make_active_user(repos, clock, ALICE_PHONE)
    await _seed(repos, clock, alice, recording_url=rec.as_uri())
    await _delete_via_chat(pipeline, channel, fake_brain)
    assert not rec.exists()
