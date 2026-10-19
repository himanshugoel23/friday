"""End to end, offline: WhatsApp message -> understand -> approval -> gate -> task engine job ->
W2 engine against a simulated callee persona -> report with next-action buttons.

Scenarios (a) the happy path, (b) refusals / do-not-call / stop calling / wrong number / voicemail,
(c) a group call. No network, invented numbers.
"""

from __future__ import annotations

from datetime import timedelta

from friday.calls.models import CallStatus
from tests.integration.conftest import (
    MUMMY,
    PAPA,
    SIS,
    World,
    add_contact,
)

LATE = "mummy ko phone karke bata do ki main late hoon"


async def _setup_mummy(w: World, persona: str | None = "friendly_elder") -> None:
    if persona:
        w.telephony.assign(MUMMY, persona)
    await add_contact(w, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother")


async def _requests(w: World):  # noqa: ANN202
    return await w.c.repos.consumer_calls.list_for_user(w.user.id)


# ------------------------------------------------------------------------------------- (a)
async def test_a_mummy_late_whole_flow(world: World):
    await _setup_mummy(world)
    r = await world.say(LATE)
    approval = r[-1]
    assert [b.title for b in approval.buttons] == ["Approve", "Edit", "Cancel"]
    assert "main late hoon" in approval.text  # the user's own words
    assert "Rahul ki assistant" in approval.text  # the exact opening the call will use
    assert world.telephony.dialled == []  # nothing is dialled before the tap

    await world.tap("Approve")
    (req,) = await _requests(world)
    assert req.status == CallStatus.SCHEDULED  # gate allowed it, a job exists
    assert world.telephony.dialled == []  # scheduled, not yet dialled

    await world.run_jobs()  # the task engine's job -> CallOrchestrator.execute -> W2 engine
    assert world.telephony.dialled == [MUMMY]
    (req,) = await _requests(world)
    assert req.status == CallStatus.COMPLETED and req.attempts == 1

    report = world.channel.last_to(world.phone)
    assert report is not None and "Mummy se baat ho gayi" in (report.text or "")
    assert {b.title for b in report.buttons} == {"Theek hai", "Reminder lagao", "Phir call karo"}

    # the opening spoken on the (simulated) line is exactly the one the user approved
    brief = await world.c.repos.consumer_calls.get_brief(req.id)
    spoken_first = world.telephony.lines[0].spoken[0][0]
    assert brief is not None and brief.is_approved_as_is()
    assert spoken_first == brief.opening_line
    assert "Rahul" in spoken_first and "virtual assistant" in spoken_first  # disclosure, fixed

    # "Phir call karo" re-uses the approved plan: a second, separate call through the same path
    await world.tap("Phir call")
    await world.run_jobs()
    assert world.telephony.dialled == [MUMMY, MUMMY]
    reqs = await _requests(world)
    assert len(reqs) == 2 and all(q.status == CallStatus.COMPLETED for q in reqs)


async def test_a_redelivered_message_makes_no_second_request(world: World):
    await _setup_mummy(world)
    msg = world.channel.make_inbound(world.phone, LATE)
    await world.runtime.handle(msg)
    n = len(world.channel.messages_to(world.phone))
    await world.runtime.handle(msg.model_copy(update={"id": "again"}))  # same provider message id
    assert len(world.channel.messages_to(world.phone)) == n
    assert len(await _requests(world)) == 1


async def test_a_cancel_and_edit_never_dial(world: World):
    await _setup_mummy(world)
    await world.say(LATE)
    await world.tap("Cancel")
    await world.run_jobs()
    assert world.telephony.dialled == []
    (req,) = await _requests(world)
    assert req.status == CallStatus.CANCELLED


# ------------------------------------------------------------------------------------- (b)
async def test_b_harassment_is_refused_before_anything_is_stored(world: World):
    await _setup_mummy(world)
    r = await world.say("mummy ko 100 baar call karo jab tak uthaye nahi")
    assert r and not r[-1].buttons  # a refusal, no approval buttons
    await world.run_jobs()
    assert world.telephony.dialled == []
    assert await _requests(world) == []


async def test_b_do_not_call_callee_is_never_dialled(world: World):
    await _setup_mummy(world)
    await world.consumer.calls.orchestrator.dnc.add(MUMMY, "user_request")
    await world.say(LATE)
    r = await world.tap("Approve")
    await world.run_jobs()
    assert world.telephony.dialled == []
    (req,) = await _requests(world)
    assert req.status == CallStatus.DENIED
    assert r  # the user was told, in words


async def test_b_stop_calling_records_dnc_and_no_retry(world: World):
    await _setup_mummy(world, "stop_calling")
    await world.say(LATE)
    await world.tap("Approve")
    await world.run_jobs()
    assert world.telephony.dialled == [MUMMY]
    (req,) = await _requests(world)
    assert req.status == CallStatus.CANCELLED  # opt-out stops the request
    assert await world.consumer.calls.orchestrator.dnc.is_blocked(MUMMY)
    await world.advance(hours=5)
    await world.run_jobs()
    assert world.telephony.dialled == [MUMMY]  # no retry, ever
    assert "dobara call na karein" in world.all_out()
    # a new request to the same number is now refused for this and every other user
    await world.say("mummy ko phone karke bata do ki khana kha liya")
    await world.tap("Approve")
    await world.run_jobs()
    assert world.telephony.dialled == [MUMMY]


async def test_b_wrong_number_is_apologised_blocked_and_reported(world: World):
    await _setup_mummy(world, "wrong_number")
    await world.say(LATE)
    await world.tap("Approve")
    await world.run_jobs()
    assert await world.consumer.calls.orchestrator.dnc.is_blocked(MUMMY)
    assert "galat insaan" in world.all_out()
    await world.advance(hours=5)
    await world.run_jobs()
    assert world.telephony.dialled == [MUMMY]  # not redialled


async def test_b_voicemail_is_retried_then_gives_up_with_the_final_message(world: World):
    await _setup_mummy(world, "voicemail_with_beep")
    await world.say(LATE)
    await world.tap("Approve")
    await world.run_jobs()
    (req,) = await _requests(world)
    first = world.clock.now()
    assert req.status == CallStatus.SCHEDULED and req.attempts == 1
    assert req.next_attempt_at == first + timedelta(hours=1)  # +1h
    assert "phir try karungi" in world.all_out()  # told once, not on every attempt

    await world.advance(hours=1)
    await world.run_jobs()
    (req,) = await _requests(world)
    assert req.attempts == 2 and req.next_attempt_at == world.clock.now() + timedelta(hours=3)

    await world.advance(hours=3)
    await world.run_jobs()
    (req,) = await _requests(world)
    assert req.attempts == 3 and req.status == CallStatus.FAILED  # max 3, then stop
    assert len(world.telephony.dialled) == 3
    final = world.channel.last_to(world.phone)
    assert final is not None and "voicemail" in (final.text or "")
    await world.advance(hours=10)
    await world.run_jobs()
    assert len(world.telephony.dialled) == 3


async def test_b_unreachable_number_final_message_says_it_could_not_reach(world: World):
    await _setup_mummy(world, "carrier_unreachable")
    await world.say(LATE)
    await world.tap("Approve")
    for hours in (0, 1, 3):
        await world.advance(hours=hours)
        await world.run_jobs()
    assert len(world.telephony.dialled) == 3
    final = world.channel.last_to(world.phone)
    assert final is not None and "3 baar try karne par bhi phone nahi uthaya" in (final.text or "")


async def test_b_a_call_in_progress_is_not_started_twice(world: World):
    """The same job delivered twice dials once (attempt saved before the dial)."""
    await _setup_mummy(world)
    await world.say(LATE)
    await world.tap("Approve")
    orch = world.consumer.calls.orchestrator
    (req,) = await _requests(world)
    first = await orch.execute(req.id)
    second = await orch.execute(req.id)
    assert first is not None and second is None
    assert world.telephony.dialled == [MUMMY]


# ------------------------------------------------------------------------------------- (c)
async def test_c_group_call_two_children_one_collected_report(world: World):
    world.telephony.assign(SIS, "friendly_elder")
    world.telephony.assign(PAPA, "friendly_elder")
    await add_contact(world, "Neha", SIS, relationship="friend")
    await add_contact(world, "Raj", PAPA, relationship="friend")
    r = await world.say("sabko party ke liye call karo: Raj, Neha")
    assert r and "Raj, Neha" in (r[-1].text or "")
    await world.tap("Approve")
    reqs = await _requests(world)
    parents = [q for q in reqs if q.parent_id is None]
    kids = [q for q in reqs if q.parent_id]
    assert len(parents) == 1 and len(kids) == 2
    assert all(k.status == CallStatus.SCHEDULED for k in kids)
    assert world.telephony.dialled == []

    await world.run_jobs()
    assert sorted(world.telephony.dialled) == sorted([SIS, PAPA])
    reqs = await _requests(world)
    parent = next(q for q in reqs if q.parent_id is None)
    assert parent.status == CallStatus.COMPLETED
    group = [t for t in world.texts() if "Group ka jawab" in t]
    assert len(group) == 1  # one collected result, not one message per child
    assert "Raj" in group[0] and "Neha" in group[0] and "2 ne bataya" in group[0]
    assert "Raj, Neha se ho rahi hai" not in world.all_out()  # the opening names nobody
