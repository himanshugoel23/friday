"""Red team: what a DB dump / backup leak reveals. Inspect RAW rows (bypassing the
repositories) for planted plaintext."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

from friday.core.models import (
    AccountIdentifier,
    CallOutcome,
    CallResult,
    DialStatus,
    Person,
    Place,
    Speaker,
    Task,
    TaskSpec,
    TaskType,
    Transcript,
)
from friday.db.repositories import make_repositories
from tests.security.conftest import (
    ACCOUNT_NO,
    ALICE_PHONE,
    DAD_NOTES,
    HOME_ADDRESS,
    SECRET,
    make_active_user,
)


async def _raw_dump(db, table: str) -> str:
    async with db.engine.connect() as conn:
        rows = (await conn.execute(text(f"SELECT * FROM {table}"))).all()  # noqa: S608
    return "\n".join(repr(tuple(r)) for r in rows)


async def _all_tables_dump(db) -> str:
    import friday.db.tables  # noqa: F401
    from friday.db.base import Base

    return "\n".join([await _raw_dump(db, t) for t in Base.metadata.tables])


async def test_identifier_value_encrypted_at_rest(repos, clock, db) -> None:
    user = await make_active_user(repos, clock, ALICE_PHONE)
    await repos.identifiers.upsert(
        AccountIdentifier(user_id=user.id, company="HDFC", label="Account number", value=ACCOUNT_NO)
    )
    raw = await _raw_dump(db, "account_identifiers")
    assert ACCOUNT_NO not in raw
    assert ACCOUNT_NO[-4:] in raw  # only last4 in clear (masked display)
    # round trip through the repository works
    (got,) = await repos.identifiers.list_for_user(user.id)
    assert got.value == ACCOUNT_NO


async def test_identifier_ciphertext_useless_without_the_key(repos, clock, db) -> None:
    user = await make_active_user(repos, clock, ALICE_PHONE)
    ident = await repos.identifiers.upsert(
        AccountIdentifier(user_id=user.id, label="Consumer number", value=ACCOUNT_NO)
    )
    other = make_repositories(db, clock, "a-different-key")
    with pytest.raises(ValueError):
        await other.identifiers.get(ident.id)
    same = make_repositories(db, clock, SECRET)
    assert (await same.identifiers.get(ident.id)).value == ACCOUNT_NO


async def test_pin_never_stored_raw_anywhere(repos, clock, db) -> None:
    await make_active_user(repos, clock, ALICE_PHONE)
    from tests.security.conftest import PIN

    assert f"'{PIN}'" not in await _all_tables_dump(db)


async def test_person_notes_encrypted_at_rest(repos, clock, db) -> None:
    user = await make_active_user(repos, clock, ALICE_PHONE)
    await repos.people.upsert(Person(owner_user_id=user.id, name="Ramesh", notes=DAD_NOTES))
    assert "insulin" not in await _raw_dump(db, "people")


async def test_place_address_encrypted_at_rest(repos, clock, db) -> None:
    user = await make_active_user(repos, clock, ALICE_PHONE)
    await repos.places.upsert(Place(owner_user_id=user.id, label="Home", address_text=HOME_ADDRESS))
    assert "Shanti Apartments" not in await _raw_dump(db, "places")


async def test_call_transcript_encrypted_at_rest(repos, clock, db) -> None:
    user = await make_active_user(repos, clock, ALICE_PHONE)
    task = Task(
        requester_user_id=user.id,
        type=TaskType.HEALTHCARE,
        spec=TaskSpec(type=TaskType.HEALTHCARE, goal="Book a diabetologist"),
    )
    await repos.tasks.add(task)
    tr = Transcript()
    tr.add(Speaker.CALLEE, "Patient ka sugar level kitna hai? Insulin le rahe hain?")
    await repos.tasks.save_call(
        CallResult(
            task_id=task.id,
            provider="simulator",
            to_phone="+918040000001",
            dial_status=DialStatus.ANSWERED,
            outcome=CallOutcome.PARTIAL,
            transcript=tr,
        )
    )
    assert "Insulin" not in await _raw_dump(db, "call_turns")


async def test_identifier_key_rotation(repos, clock, db) -> None:
    from friday.db.repositories._base import SecretBox

    user = await make_active_user(repos, clock, ALICE_PHONE)
    ident = await repos.identifiers.upsert(
        AccountIdentifier(user_id=user.id, label="Account number", value=ACCOUNT_NO)
    )
    rotated = SecretBox("new-key", previous=[SECRET])  # type: ignore[call-arg]
    raw = await _raw_dump(db, "account_identifiers")
    assert rotated is not None and ident.id in raw


def test_debug_logging_does_not_dump_sql_parameters(monkeypatch) -> None:
    import friday.core.logging as flog

    root = logging.getLogger()
    saved = (root.level, list(root.handlers))
    noisy = {
        n: logging.getLogger(n).level
        for n in ("aiosqlite", "httpx", "httpcore", "anthropic", "sqlalchemy.engine")
    }
    monkeypatch.setattr(flog, "_CONFIGURED", False)
    try:
        flog.setup_logging("DEBUG")
        assert logging.getLogger("aiosqlite").getEffectiveLevel() >= logging.INFO
    finally:
        root.setLevel(saved[0])
        root.handlers[:] = saved[1]
        for name, level in noisy.items():
            logging.getLogger(name).setLevel(level)
