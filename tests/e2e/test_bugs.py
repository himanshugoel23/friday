"""Bugs found by QA, each as a strict xfail (see docs/QA_REPORT.md). When the owner fixes one
the strict xfail turns into a failure: delete the marker and keep the test as a regression."""

from __future__ import annotations

import re

import pytest

from friday.core.models import TaskStatus

URBAN = "+918040001013"


@pytest.mark.xfail(
    strict=True,
    reason="BUG-2: Task.role has no column in `tasks`; fan-out children lose their role on a DB "
    "round trip, so every parallel-quote / stock-hunt / discovery flow fails with real repos",
)
async def test_parallel_quotes_work_with_the_real_repositories(raw_friday):
    rahul = raw_friday.person("+919811100001")
    await rahul.say("Indiranagar mein AC repair karne wala dhundo, 3 se quotes lo")
    await rahul.say("1")
    parent = await rahul.task(0)
    assert parent.status == TaskStatus.AWAITING_CHOICE


@pytest.mark.xfail(
    strict=True,
    reason="BUG-5: a named business is resolved to the first directory hit with a phone, with no "
    "name check: 'Urban Trim Salon' dials 'Looks Unisex Salon'",
)
async def test_named_business_is_the_one_that_gets_dialled(friday, rahul):
    await rahul.say("Urban Trim Salon mein haircut book karo kal shaam")
    t = await rahul.task()
    assert t.target is None or t.target.phone == URBAN or t.status == TaskStatus.NEEDS_INFO


@pytest.mark.xfail(
    strict=True,
    reason="BUG-9: a booking reference (LO196353) heard on the confirmation call is parsed as a "
    "price and shown to the user as 'price: ₹1,96,353'",
)
async def test_booking_reference_is_not_reported_as_a_price(friday, rahul):
    await rahul.say("Looks Unisex Salon mein haircut book karo kal shaam")
    await rahul.say("1")
    m = re.search(r"price: ₹([\d,]+)", rahul.last())
    assert m is None or int(m.group(1).replace(",", "")) <= 1000


@pytest.mark.xfail(
    strict=True,
    reason="BUG-14: the offer message repeats the question twice (summary + question text)",
)
async def test_offer_message_does_not_repeat_itself(friday, rahul):
    await rahul.say("Looks Unisex Salon mein haircut book karo kal shaam")
    lines = [x for x in rahul.last_msg().text.splitlines() if x.strip()]
    assert len(lines) == len(set(lines))


@pytest.mark.xfail(
    strict=True,
    reason="BUG-16: CallResult.from_number is never populated (it is None for every call), "
    "although call memory knows the caller-ID",
)
async def test_call_result_records_the_caller_id_used(friday, rahul):
    await rahul.say("Looks Unisex Salon mein haircut book karo kal shaam")
    (call,) = await rahul.calls(await rahul.task())
    assert call.from_number


@pytest.mark.xfail(
    strict=True,
    reason="BUG-17: delegated commit attempts that are blocked repeat ~10 times (callee hears "
    "'Maaf kijiye' each time) before the call is wrapped up; ~64k LLM tokens burnt per call",
)
async def test_blocked_commit_does_not_loop(friday, rahul):
    await rahul.say(
        "Looks Unisex Salon mein haircut book karo kal shaam 4-7 ke beech koi bhi slot, "
        "₹800 tak, aap decide karo"
    )
    (call,) = await rahul.calls(await rahul.task())
    blocked = [x for x in call.transcript.turns if x.text.startswith("BLOCKED")]
    assert len(blocked) <= 2


@pytest.mark.xfail(
    strict=True,
    reason="BUG-6: the telephony simulator only schedules a scripted call-back "
    "(`sim:calls_back_after`) "
    "after an ANSWERED outbound call, so the 'Urban Trim' persona (never answers, rings back "
    "after seeing the missed call) can never ring back",
)
async def test_missed_call_persona_rings_back_by_itself(friday, rahul):
    await rahul.say("Urban Trim Salon +918040001013 mein haircut book karo kal shaam")
    await friday.advance(minutes=45)
    assert friday.c.telephony.inbound_log, "the scripted call-back never happened"
