"""Delegated booking (limits), mid-call clarification question, no-answer retries."""

from __future__ import annotations

import asyncio
import json

import pytest

from friday.core.clock import to_ist
from friday.core.models import CallOutcome, TaskStatus
from tests.e2e.harness import callee_lines, friday_lines

LOOKS = "+918040000001"
FROSTY = "+918040000004"
DELEGATED = "Looks Unisex Salon mein haircut book karo kal shaam 4-7 ke beech koi bhi slot, {cap} tak, aap decide karo"


@pytest.mark.xfail(
    strict=True,
    reason="BUG-1: the call policy never sets CallAction.slot_at, so check_commit can never "
    "verify a delegation WINDOW; a delegated booking always degrades to PENDING_APPROVAL",
)
async def test_delegated_booking_is_confirmed_on_the_call_within_limits(friday, rahul):
    await rahul.say(DELEGATED.format(cap="₹800"))
    t = await rahul.task()
    assert t.status == TaskStatus.COMPLETED
    calls = await rahul.calls(t)
    assert len(calls) == 1 and calls[0].outcome == CallOutcome.SUCCESS
    assert calls[0].collected.get("committed") == "true"


async def test_delegation_outside_the_price_limit_is_refused_on_the_call(friday, rahul):
    await rahul.say(DELEGATED.format(cap="₹300"))  # the salon charges ₹400
    t = await rahul.task()
    assert t.status == TaskStatus.AWAITING_APPROVAL  # falls back to the call-back rule
    calls = await rahul.calls(t)
    assert len(calls) == 1 and calls[0].outcome == CallOutcome.PENDING_APPROVAL
    assert "committed" not in calls[0].collected
    assert "call back" in " ".join(friday_lines(calls[0])).lower()
    assert t.approved_terms is None


async def test_delegation_never_leaks_into_other_tasks(friday, rahul):
    await rahul.say(DELEGATED.format(cap="₹300"))
    await rahul.say("Dr. Sharma's Family Clinic mein appointment book karo kal subah")
    t = await rahul.task()
    assert not t.delegation.granted and not t.spec.delegation.granted
    assert t.status == TaskStatus.AWAITING_APPROVAL


async def test_mid_call_clarification_question_is_relayed_and_answered(friday, rahul):
    """The business is on hold while the user answers a question that arrives on WhatsApp."""
    friday.c.llm.script(
        "call_turn",
        json.dumps(
            {
                "type": "ask_user",
                "text": "Ek minute ji, main check kar rahi hoon.",
                "language": "hinglish",
                "question": {
                    "text": "Salon pooch raha hai: beard trim bhi chahiye?",
                    "purpose": "clarify",
                    "options": ["Haan", "Nahi"],
                },
                "collected": [],
            }
        ),
    )
    seen = len(rahul.msgs())
    run = asyncio.create_task(
        rahul.say("Looks Unisex Salon mein haircut book karo kal shaam")
    )
    await rahul.ch.wait_for(rahul.phone, seen + 2, timeout_s=15)
    t = await rahul.task()
    assert t.status == TaskStatus.AWAITING_USER
    q = rahul.last_msg()
    assert "beard trim" in q.text and [b.title for b in q.buttons] == ["Haan", "Nahi"]

    await rahul.say("1")  # "Haan"
    await run
    t = await rahul.task()
    assert t.status == TaskStatus.AWAITING_APPROVAL  # call carried on to the offer
    (call,) = await rahul.calls(t)
    system = [x.text for x in call.transcript.turns if x.speaker.value == "system"]
    assert any("USER ANSWERED: Haan" in s for s in system)
    holds = [line for line in friday_lines(call) if "intezaar" in line or "check" in line]
    assert holds, friday_lines(call)  # the business got a polite hold line, not silence
    assert callee_lines(call)  # and the call resumed afterwards


async def test_no_answer_three_tries_one_notification_then_options(friday, rahul):
    await rahul.say("Frosty Air Solutions ko call karke AC repair ke liye bolo")
    t = await rahul.task()
    assert t.status == TaskStatus.SCHEDULED
    await friday.advance(minutes=20)
    await friday.advance(minutes=60)
    t = await rahul.task()
    assert t.status == TaskStatus.FAILED and t.attempts == 3
    calls = await rahul.calls(t)
    assert len(calls) == 3 and all(c.outcome == CallOutcome.BUSY for c in calls)
    texts = rahul.texts()
    # exactly ONE "not picking up" notification across the retries
    assert sum("isn't picking up" in x for x in texts) == 1, texts
    final = texts[-1]
    assert "3 tries" in final
    assert [b.title for b in rahul.last_msg().buttons] == [
        "Later today",
        "Tomorrow",
        "Another business",
    ]


async def test_final_options_work_try_tomorrow(friday, rahul):
    await rahul.say("Frosty Air Solutions ko call karke AC repair ke liye bolo")
    await friday.advance(minutes=20)
    await friday.advance(minutes=60)
    await rahul.say("2")  # Tomorrow
    tasks = sorted(await rahul.tasks(), key=lambda x: x.created_at)
    retry = tasks[-1]
    assert retry.status == TaskStatus.SCHEDULED
    assert to_ist(retry.next_attempt_at).date() > to_ist(friday.clock.now()).date()
    assert 9 <= to_ist(retry.next_attempt_at).hour < 21  # inside the call window
