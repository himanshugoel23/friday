"""Proactive cap / quiet hours, delete everything, number pool (sticky + pool-wide DNC)."""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.core.clock import IST, to_ist
from friday.core.models import Fact, FactKind, NudgeStatus, TaskStatus
from tests.e2e.conftest import RAHUL
from tests.e2e.harness import PIN

LOOKS = "+918040000001"


async def _facts(friday, rahul, keys, due_in_days=1):
    user = await rahul.user_row()
    today = to_ist(friday.clock.now()).date()
    for k in keys:
        await friday.c.repos.facts.upsert(
            Fact(user_id=user.id, kind=FactKind.DATE, key=k, value=k,
                 due_on=today + timedelta(days=due_in_days))
        )


async def test_proactive_daily_cap_is_three_per_ist_day(friday, rahul):
    await _facts(friday, rahul, ["rent_due0", "emi_due1", "bill_due2", "fee_due3"])
    before = len(rahul.msgs())
    pe = friday.c.proactive
    await pe.tick()
    await pe.drain()
    nudges = [m for m in rahul.msgs()[before:] if m.nudge_id]
    assert len(nudges) == 3
    repo = friday.c.repos.nudges
    user = await rahul.user_row()
    all_n = await repo.list_for_user(user.id)
    suppressed = [n for n in all_n if n.status == NudgeStatus.SUPPRESSED]
    assert len(suppressed) == 1 and "cap" in (suppressed[0].reason or "")
    # no nudge is a dead end: each carries a way to postpone or dismiss it
    assert all(len(m.buttons) == 3 for m in nudges)


async def test_proactive_nudges_wait_for_quiet_hours_to_end(friday, rahul):
    friday.clock.set(datetime(2026, 1, 5, 23, 0, tzinfo=IST))
    await _facts(friday, rahul, ["rent_due0"])
    before = len(rahul.msgs())
    await friday.c.proactive.tick()
    await friday.c.proactive.drain()
    assert [m for m in rahul.msgs()[before:] if m.nudge_id] == []  # 23:00 IST: silence
    friday.clock.set(datetime(2026, 1, 6, 9, 0, tzinfo=IST))
    await friday.c.proactive.tick()
    await friday.c.proactive.drain()
    assert [m for m in rahul.msgs()[before:] if m.nudge_id]  # morning: delivered


async def test_dismissed_nudge_is_not_repeated(friday, rahul):
    await _facts(friday, rahul, ["rent_due0"])
    await friday.c.proactive.tick()
    await friday.c.proactive.drain()
    nudge_msg = next(m for m in reversed(rahul.msgs()) if m.nudge_id)
    assert nudge_msg.buttons[2].title == "Not needed"
    await rahul.say("3")
    user = await rahul.user_row()
    (n,) = await friday.c.repos.nudges.list_for_user(user.id)
    assert n.status != NudgeStatus.SENT
    before = len(rahul.msgs())
    await friday.advance(hours=3)
    await friday.c.proactive.tick()
    await friday.c.proactive.drain()
    assert [m for m in rahul.msgs()[before:] if m.nudge_id] == []


async def test_delete_everything_needs_pin_and_confirmation_and_erases_the_user(friday, rahul):
    await rahul.say("Looks Unisex Salon mein haircut book karo kal shaam")
    await rahul.say("delete everything")
    assert "PIN" in rahul.last()
    assert await friday.c.repos.users.get_by_phone(RAHUL) is not None  # not yet
    await rahul.say(PIN)
    assert "DELETE" in rahul.last()
    assert await friday.c.repos.users.get_by_phone(RAHUL) is not None  # still waiting
    await rahul.say("DELETE")
    assert await friday.c.repos.users.get_by_phone(RAHUL) is None


async def test_wrong_pin_never_deletes(friday, rahul):
    await rahul.say("delete everything")
    await rahul.say("9999")
    await rahul.say("DELETE")
    assert await friday.c.repos.users.get_by_phone(RAHUL) is not None


# ---------------------------------------------------------------- number pool
async def _friday_numbers_used(friday, business_phone):
    since = friday.clock.now().replace(year=2025)
    mem = await friday.c.repos.calls.recent_for_phone(business_phone, since=since, limit=50)
    return {m.friday_number for m in mem}


async def test_number_is_sticky_per_business_across_users_and_attempts(friday, rahul, priya):
    await rahul.say("Looks Unisex Salon mein haircut book karo kal shaam")
    await rahul.say("1")
    await priya.say("Looks Unisex Salon mein haircut book karo kal shaam")
    await priya.say("1")
    used = await _friday_numbers_used(friday, LOOKS)
    assert len(used) == 1, used  # same business -> same Friday number, always (4 calls)
    assert used <= set(friday.c.telephony.friday_numbers)


async def test_different_businesses_may_use_different_numbers_but_each_is_sticky(friday, rahul):
    await rahul.say("Dr. Sharma's Family Clinic mein appointment book karo kal subah")
    await rahul.say("1")
    await rahul.say("Looks Unisex Salon mein haircut book karo kal shaam")
    await rahul.say("1")
    for phone in (LOOKS, "+912040000002"):
        assert len(await _friday_numbers_used(friday, phone)) == 1


async def test_dnc_blocks_every_number_in_the_pool_and_every_user(friday, rahul, priya):
    await friday.engine.pool.block(LOOKS, "dnc_request")
    for p in (rahul, priya):
        await p.say("Looks Unisex Salon mein haircut book karo kal shaam")
        t = await p.task()
        assert not await p.calls(t)
        assert t.status in (TaskStatus.FAILED, TaskStatus.CANCELLED)
    assert friday.c.telephony.legs == []  # rotation is never used to get around a DNC
    await friday.advance(days=2)
    assert friday.c.telephony.legs == []
