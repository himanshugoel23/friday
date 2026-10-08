"""Business missed calls / call-backs, late call-backs after the task resolved."""

from __future__ import annotations

import pytest

from friday.core.models import CallDirection, TaskStatus
from tests.e2e.harness import friday_lines

URBAN = "+918040001013"  # no_answer persona, rings back
ASK = "Urban Trim Salon +918040001013 mein haircut book karo kal shaam"


async def _friday_number(friday, phone: str) -> str:
    since = friday.clock.now().replace(year=2025)
    mem = await friday.c.repos.calls.recent_for_phone(phone, since=since, limit=5)
    return mem[0].friday_number


async def test_business_calls_back_on_the_number_that_missed_it(friday, rahul):
    await rahul.say(ASK)
    t = await rahul.task()
    assert t.status == TaskStatus.SCHEDULED  # no answer -> retry queued
    fn = await _friday_number(friday, URBAN)
    await friday.c.telephony.simulate_inbound_call(URBAN, fn, answered=True)
    await friday.settle()
    t = await rahul.task()
    calls = await rahul.calls(t)
    inbound = [c for c in calls if c.direction == CallDirection.INBOUND]
    assert len(inbound) == 1
    lines = friday_lines(inbound[0])
    assert "ai assistant" in lines[0].lower()  # disclosure first on inbound too
    assert "Rahul" in lines[0]  # context only for a verified, matched caller
    # the approval rule still holds on the call-back: the offer goes to the user
    assert t.status == TaskStatus.AWAITING_APPROVAL
    assert "committed" not in inbound[0].collected


async def test_unknown_caller_learns_nothing_about_any_user(friday, rahul):
    await rahul.say(ASK)
    await friday.c.telephony.simulate_inbound_call("+919845099999", answered=True)
    await friday.settle()
    for c in await rahul.calls(await rahul.task()):
        if c.direction == CallDirection.INBOUND:
            blob = " ".join(friday_lines(c))
            assert "Rahul" not in blob and "haircut" not in blob.lower()


async def test_missed_call_from_a_business_triggers_one_prompt_call_back(friday, rahul):
    await rahul.say(ASK)
    t = await rahul.task()
    attempts_before = len(await rahul.calls(t))
    fn = await _friday_number(friday, URBAN)
    await friday.c.telephony.simulate_inbound_call(URBAN, fn, answered=False)
    await friday.settle()
    t = await rahul.task()
    # the missed call pulls the next attempt forward (one extra call, not a flurry)
    assert len(await rahul.calls(t)) == attempts_before + 1
    assert len([x for x in rahul.texts() if "isn't picking up" in x]) == 1


async def test_late_callback_after_the_user_cancelled_is_closed_politely(friday, rahul):
    await rahul.say(ASK)
    await rahul.say("cancel")
    t = await rahul.task()
    assert t.status == TaskStatus.CANCELLED
    fn = await _friday_number(friday, URBAN)
    await friday.advance(hours=3)  # retries must not fire after the cancel
    assert (await rahul.task(0)).status == TaskStatus.CANCELLED
    await friday.c.telephony.simulate_inbound_call(URBAN, fn, answered=True)
    await friday.settle()
    inbound = [
        c
        for tk in await rahul.tasks()
        for c in await rahul.calls(tk)
        if c.direction == CallDirection.INBOUND
    ]
    assert len(inbound) == 1
    # nothing is committed, the cancelled task stays cancelled and no retry is revived
    assert "committed" not in inbound[0].collected
    assert (await rahul.task(0)).status == TaskStatus.CANCELLED
    assert not [x for x in rahul.texts() if "Ho gaya" in x]


async def test_late_callback_close_loop_script_is_used(friday, rahul):
    await rahul.say(ASK)
    await rahul.say("cancel")
    fn = await _friday_number(friday, URBAN)
    await friday.c.telephony.simulate_inbound_call(URBAN, fn, answered=True)
    await friday.settle()
    for tk in await rahul.tasks():
        for c in await rahul.calls(tk):
            if c.direction == CallDirection.INBOUND:
                said = " ".join(friday_lines(c)).lower()
                assert "kitna" not in said and "khule" not in said
