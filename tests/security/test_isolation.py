"""Red team: cross-user data isolation (repositories, context builder, button payloads).

Attacker model: a legitimate Friday user (Bob) trying to read or alter another
user's (Alice's) data - via ids leaked in screenshots, forged WhatsApp button
payloads (unofficial clients can send any button id), or a prompt-injected brain
that echoes foreign ids back.
"""

from __future__ import annotations

import pytest

from friday.core.models import (
    AccountIdentifier,
    Fact,
    FactKind,
    InboundMessage,
    Intent,
    Interpretation,
    MessageKind,
    MidCallQuestion,
    Nudge,
    NudgeKind,
    AutonomyCategory,
    Person,
    Place,
    QuestionPurpose,
    Task,
    TaskSpec,
    TaskStatus,
    TaskType,
    approval_button_id,
    nudge_button_id,
    question_button_id,
)
from tests.security.conftest import (
    ACCOUNT_NO,
    ALICE_PHONE,
    BOB_PHONE,
    DAD_NOTES,
    DAD_PHONE,
    HOME_ADDRESS,
    make_active_user,
)


async def _seed_alice(repos, clock):
    alice = await make_active_user(repos, clock, ALICE_PHONE)
    dad = await repos.people.upsert(
        Person(owner_user_id=alice.id, name="Ramesh", relation="father", phone=DAD_PHONE,
               notes=DAD_NOTES)
    )
    home = await repos.places.upsert(
        Place(owner_user_id=alice.id, label="Home", address_text=HOME_ADDRESS)
    )
    fact = await repos.facts.upsert(
        Fact(user_id=alice.id, kind=FactKind.GENERAL, key="dad_bp", value="BP check every month")
    )
    ident = await repos.identifiers.upsert(
        AccountIdentifier(user_id=alice.id, company="Airtel", label="Account number",
                          value=ACCOUNT_NO)
    )
    task = Task(
        requester_user_id=alice.id,
        type=TaskType.BOOKING,
        status=TaskStatus.AWAITING_USER,
        spec=TaskSpec(type=TaskType.BOOKING, goal="Book a haircut", business_phone="+918040000001"),
    )
    await repos.tasks.add(task)
    question = await repos.tasks.add_question(
        MidCallQuestion(task_id=task.id, text="Book 6pm for ₹400?",
                        purpose=QuestionPurpose.APPROVE_BOOKING, options=["Yes, book 6pm", "No"],
                        timeout_s=0, asked_at=clock.now())
    )
    return alice, dad, home, fact, ident, task, question


async def test_list_queries_are_owner_scoped(repos, clock) -> None:
    alice, *_ = await _seed_alice(repos, clock)
    bob = await make_active_user(repos, clock, BOB_PHONE)
    assert await repos.people.list_for_owner(bob.id) == []
    assert await repos.places.list_for_owner(bob.id, include_ephemeral=True) == []
    assert await repos.facts.list_for_user(bob.id) == []
    assert await repos.identifiers.list_for_user(bob.id) == []
    assert await repos.tasks.list_for_user(bob.id) == []
    assert await repos.tasks.open_question_for_user(bob.id) is None
    assert len(await repos.people.list_for_owner(alice.id)) == 1


async def test_context_builder_contains_only_own_data(repos, clock) -> None:
    from friday.api.context import build_context

    await _seed_alice(repos, clock)
    bob = await make_active_user(repos, clock, BOB_PHONE)
    ctx = await build_context(repos, clock, bob)
    dumped = ctx.model_dump_json()
    assert DAD_NOTES not in dumped and HOME_ADDRESS not in dumped and "Ramesh" not in dumped
    assert ctx.people == [] and ctx.places == [] and ctx.facts == [] and ctx.open_tasks == []
    assert ACCOUNT_NO not in dumped


async def test_brain_never_sees_identifier_values(repos, clock) -> None:
    from friday.api.context import build_context

    alice, *_ = await _seed_alice(repos, clock)
    ctx = await build_context(repos, clock, alice)
    assert ACCOUNT_NO not in ctx.model_dump_json()


async def test_forged_approval_button_for_foreign_task_is_ignored(
    repos, clock, pipeline, fake_engine
) -> None:
    *_, task, _q = await _seed_alice(repos, clock)
    bob = await make_active_user(repos, clock, BOB_PHONE)
    await pipeline.handle(
        InboundMessage(channel="simulator", from_phone=bob.phone, kind=MessageKind.BUTTON_REPLY,
                       text="Yes", button_id=approval_button_id(task.id, True))
    )
    assert "approve" not in fake_engine.names()
    assert (await repos.tasks.get(task.id)).status == TaskStatus.AWAITING_USER


async def test_forged_nudge_button_for_foreign_nudge_is_ignored(repos, clock, pipeline) -> None:
    alice, *_ = await _seed_alice(repos, clock)
    nudge = Nudge(user_id=alice.id, kind=NudgeKind.PATTERN, category=AutonomyCategory.ROUTINES,
                  dedupe_key="pattern:haircut",
                  proposed_task=TaskSpec(type=TaskType.BOOKING, goal="haircut"))
    await repos.nudges.add(nudge)
    bob = await make_active_user(repos, clock, BOB_PHONE)
    await pipeline.handle(
        InboundMessage(channel="simulator", from_phone=bob.phone, kind=MessageKind.BUTTON_REPLY,
                       text="Book", button_id=nudge_button_id(nudge.id, "book"))
    )
    assert await repos.tasks.list_for_user(bob.id) == []
    stored = await repos.nudges.get(nudge.id)
    assert stored.responded_at is None


@pytest.mark.xfail(
    strict=True,
    reason="SECURITY-9: q:<question_id> button answers are not checked against the sender "
    "(another user can approve someone else's booking)",
)
async def test_forged_question_button_for_foreign_question_is_ignored(
    repos, clock, pipeline
) -> None:
    *_, question = await _seed_alice(repos, clock)
    bob = await make_active_user(repos, clock, BOB_PHONE)
    await pipeline.handle(
        InboundMessage(channel="simulator", from_phone=bob.phone, kind=MessageKind.BUTTON_REPLY,
                       text="Yes, book 6pm", button_id=question_button_id(question.id, 0))
    )
    assert await repos.tasks.get_answer(question.id) is None


async def test_brain_supplied_foreign_person_id_is_not_overwritten(
    repos, clock, pipeline, fake_brain
) -> None:
    _alice, dad, *_ = await _seed_alice(repos, clock)
    bob = await make_active_user(repos, clock, BOB_PHONE)
    evil = Person(id=dad.id, owner_user_id=bob.id, name="Mallory", phone="+919000000000")
    fake_brain.script.append(Interpretation(intent=Intent.ADD_PERSON, person_upsert=evil))
    await pipeline.handle(
        InboundMessage(channel="simulator", from_phone=bob.phone, text="add mallory")
    )
    stored = await repos.people.get(dad.id)
    assert stored.owner_user_id == dad.owner_user_id and stored.notes == DAD_NOTES


async def test_brain_supplied_foreign_place_id_is_not_overwritten(
    repos, clock, pipeline, fake_brain
) -> None:
    _alice, _dad, home, *_ = await _seed_alice(repos, clock)
    bob = await make_active_user(repos, clock, BOB_PHONE)
    evil = Place(id=home.id, owner_user_id=bob.id, label="Mine now", address_text="elsewhere")
    fake_brain.script.append(Interpretation(intent=Intent.ADD_PLACE, place_upsert=evil))
    await pipeline.handle(InboundMessage(channel="simulator", from_phone=bob.phone, text="save"))
    stored = await repos.places.get(home.id)
    assert stored.owner_user_id == home.owner_user_id and stored.address_text == HOME_ADDRESS


@pytest.mark.xfail(
    strict=True,
    reason="SECURITY-10: facts are upserted by id without an owner check "
    "(a foreign fact id re-assigns/overwrites another user's memory)",
)
async def test_brain_supplied_foreign_fact_id_is_not_overwritten(
    repos, clock, pipeline, fake_brain
) -> None:
    _alice, _dad, _home, fact, *_ = await _seed_alice(repos, clock)
    bob = await make_active_user(repos, clock, BOB_PHONE)
    evil = Fact(id=fact.id, user_id=bob.id, kind=FactKind.GENERAL, key="x", value="hijacked")
    fake_brain.script.append(Interpretation(intent=Intent.REMEMBER, facts=[evil]))
    await pipeline.handle(InboundMessage(channel="simulator", from_phone=bob.phone, text="note"))
    stored = await repos.facts.get(fact.id)
    assert stored.user_id == fact.user_id and stored.value == fact.value


@pytest.mark.xfail(
    strict=True,
    reason="SECURITY-10: identifiers are upserted by id without an owner check",
)
async def test_identifier_upsert_with_foreign_id_does_not_steal_row(repos, clock) -> None:
    *_, ident, _task, _q = await _seed_alice(repos, clock)
    bob = await make_active_user(repos, clock, BOB_PHONE)
    await repos.identifiers.upsert(
        AccountIdentifier(id=ident.id, user_id=bob.id, label="Mine", value="111122223333")
    )
    stored = await repos.identifiers.get(ident.id)
    assert stored.user_id == ident.user_id and stored.value == ACCOUNT_NO
