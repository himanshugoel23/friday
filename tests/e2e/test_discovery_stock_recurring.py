"""Discovery -> shortlist -> parallel quotes -> comparison -> booking; stock hunt first match;
recurring booking."""

from __future__ import annotations

from friday.core.models import CallOutcome, TaskStatus, TaskType
from tests.e2e.harness import friday_lines

COOL, CHILL, FROSTY = "+918040000003", "+918040000005", "+918040000004"
CITY_CHEMIST = "+912040000007"


async def test_discovery_shortlist_parallel_quotes_comparison_booking(friday, rahul):
    await rahul.say("Indiranagar mein AC repair karne wala dhundo, 3 se quotes lo")
    parent = await rahul.task()
    assert parent.type == TaskType.QUOTE and parent.status == TaskStatus.AWAITING_APPROVAL
    shortlist = rahul.last()
    for name in ("CoolCare AC Services", "Chill Point AC Repair", "Frosty Air Solutions"):
        assert name in shortlist
    assert not await rahul.calls(parent)  # nobody is called before the user says go

    await rahul.say("1")  # "Call all 3"
    tasks = await rahul.tasks()
    children = [t for t in tasks if t.parent_task_id == parent.id]
    assert len(children) == 3
    by_name = {c.target.name: c for c in children}
    # parallel quote calls: the two reachable shops gave offers, the busy one was dropped
    assert by_name["CoolCare AC Services"].status == TaskStatus.COMPLETED
    assert by_name["Chill Point AC Repair"].status == TaskStatus.COMPLETED
    assert by_name["Frosty Air Solutions"].status == TaskStatus.CANCELLED
    for name in ("CoolCare AC Services", "Chill Point AC Repair"):
        (call,) = await rahul.calls(by_name[name])
        assert "committed" not in call.collected  # quote calls never commit
    parent = await rahul.task(0)
    assert parent.status == TaskStatus.AWAITING_CHOICE
    comparison = rahul.last()
    assert "₹550" in comparison and "₹699" in comparison and "Meri pick" in comparison
    titles = [b.title for b in rahul.last_msg().buttons]
    assert titles[0].startswith("Book Chill Point") and titles[-1] == "None"

    await rahul.say("1")  # book the recommended one
    tasks = await rahul.tasks()
    booking = next(t for t in tasks if t.type == TaskType.BOOKING)
    assert booking.target.name == "Chill Point AC Repair"
    assert booking.status == TaskStatus.COMPLETED
    assert "Sun 10 AM" in (booking.approved_terms or "")
    (call,) = await rahul.calls(booking)
    assert call.outcome == CallOutcome.SUCCESS and call.to_phone == CHILL
    parent = next(t for t in tasks if t.id == parent.id)
    assert parent.status == TaskStatus.COMPLETED
    assert "Chill Point AC Repair" in rahul.last()


async def test_choosing_none_of_the_offers_books_nothing(friday, rahul):
    await rahul.say("Indiranagar mein AC repair karne wala dhundo, 3 se quotes lo")
    await rahul.say("1")
    await rahul.say("3")  # None
    tasks = await rahul.tasks()
    assert not [t for t in tasks if t.type == TaskType.BOOKING]
    assert (await rahul.task(0)).status == TaskStatus.CANCELLED


async def test_shortlist_can_be_declined_with_no_calls_made(friday, rahul):
    await rahul.say("Indiranagar mein AC repair karne wala dhundo, 3 se quotes lo")
    await rahul.say("2")  # Cancel
    (parent,) = await rahul.tasks()
    assert parent.status == TaskStatus.CANCELLED
    assert friday.c.telephony.legs == []


async def test_stock_hunt_stops_at_first_match_and_cancels_the_siblings(friday, priya):
    await priya.say("Kothrud mein kis chemist ke paas Dolo 650 stock hai? sab ko call karo")
    tasks = sorted(await priya.tasks(), key=lambda t: t.created_at)
    parent = next(t for t in tasks if t.parent_task_id is None)
    children = [t for t in tasks if t.parent_task_id == parent.id]
    assert parent.type == TaskType.STOCK_HUNT and parent.status == TaskStatus.COMPLETED
    assert len(children) == 3
    # first match wins: nothing is left running or retrying
    assert all(c.status.is_terminal for c in children)
    assert all(c.attempts <= 1 for c in children)  # a stock hunt never retries a shop
    reports = [x for x in priya.texts() if x.startswith("Mil gaya")]
    assert len(reports) == 1  # one answer, not one per shop


async def test_stock_hunt_reports_a_shop_that_really_has_it(friday, priya):
    await priya.say("Kothrud mein kis chemist ke paas Dolo 650 stock hai? sab ko call karo")
    tasks = await priya.tasks()
    winners = []
    for t in tasks:
        if t.parent_task_id and t.status == TaskStatus.COMPLETED:
            calls = await priya.calls(t)
            if any(c.outcome == CallOutcome.SUCCESS for c in calls):
                winners.append(t)
    # BUG-8: only the shop that answered "haan, hai" wins - not "phir se boliye?"
    assert [w.target.phone for w in winners] == [CITY_CHEMIST]
    assert "City Chemist" in priya.all_text()


async def test_recurring_booking_runs_each_cycle_within_the_standing_delegation(friday, rahul):
    await rahul.say(
        "Looks Unisex Salon mein har mahine ki 5 tareekh ko haircut book karna, "
        "₹500 tak aap decide karo"
    )
    series = await rahul.task()
    assert series.type == TaskType.RECURRING_BOOKING and series.status == TaskStatus.SCHEDULED
    assert series.recurrence is not None and series.recurrence.delegation.granted
    assert "Series set up" in rahul.last()
    assert not await rahul.calls(series)

    await friday.advance(days=31)
    instances = [t for t in await rahul.tasks() if t.type == TaskType.BOOKING]
    assert len(instances) == 1
    inst = instances[0]
    assert inst.status == TaskStatus.COMPLETED and inst.parent_task_id == series.id
    (call,) = await rahul.calls(inst)
    # the standing delegation lets this one be confirmed on the call (price <= ₹500)
    assert call.outcome == CallOutcome.SUCCESS and call.collected.get("committed") == "true"
    series = await friday.c.repos.tasks.get(series.id)
    assert series.status == TaskStatus.SCHEDULED  # next cycle is queued
    assert "AI assistant" in friday_lines(call)[0]
