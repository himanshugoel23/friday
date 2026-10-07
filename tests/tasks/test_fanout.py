"""Discovery -> shortlist -> SEQUENTIAL/PARALLEL/FIRST_MATCH children -> comparison ->
choice -> booking child (confirmation call-back); hotels hybrid + reconfirm."""

import asyncio
from datetime import date

from friday.core.clock import to_ist
from friday.core.models import (
    AutonomyCategory,
    AutonomyLevel,
    AutonomySetting,
    CallOutcome,
    Delegation,
    FanOutPolicy,
    FanOutStrategy,
    StayRequest,
    TaskSpec,
    TaskStatus as S,
    TaskType,
    approval_button_id,
    question_button_id,
)
from friday.tasks.engine import ROLE_FANOUT, ROLE_RECONFIRM, role_of
from tests.tasks.conftest import CHILL, COOL, FROSTY
from tests.tasks.fakes import offer_then_confirm, outcome, quote, result

AC = TaskSpec(type=TaskType.DISCOVERY, goal="AC service for 2 split ACs", discovery_query="AC repair",
              location_text="Indiranagar Bengaluru")


def children(env, parent_id):
    return [t for t in env.repos.tasks.items.values() if t.parent_task_id == parent_id]


async def test_discovery_sequential_compare_choose_book(env):
    env.runner.script(COOL, offer_then_confirm("CoolCare", 699, ("Sat 11am",)))
    env.runner.script(FROSTY, outcome(CallOutcome.BUSY))
    env.runner.script(CHILL, offer_then_confirm("Chill Point", 550, ("Sun 10am",)))
    t = await env.task(AC)
    assert t.status == S.AWAITING_APPROVAL and len(t.shortlist) == 3
    assert "shortlist" in env.texts()[-1] and env.notifier.last().buttons[0].title == "Call all 3"
    await env.engine.handle_button(env.user.id, approval_button_id(t.id, True))
    await env.engine.drain()
    t = await env.get(t.id)
    assert env.runner.max_active == 1  # sequential
    assert t.status == S.AWAITING_CHOICE
    kids = children(env, t.id)
    assert all(role_of(k) == ROLE_FANOUT and k.type == TaskType.QUOTE for k in kids)
    frosty = next(k for k in kids if k.target.phone == FROSTY)
    assert frosty.status == S.CANCELLED  # pending retry cancelled once resolved enough
    # later calls carry earlier quotes as leverage; compare calls never commit
    chill_brief = next(b for b in env.runner.briefs if b.target.phone == CHILL)
    assert [q.business_name for q in chill_brief.competing_quotes] == ["CoolCare"]
    assert all(not b.can_commit([]) for b in env.runner.briefs)
    assert [q.business_name for q in t.result.comparison.ranked_quotes] == ["Chill Point", "CoolCare"]
    msg = env.notifier.last()
    assert [b.title for b in msg.buttons] == ["Book Chill Point", "Book CoolCare", "None"]
    # the tap is the approval -> booking child -> confirmation call-back
    await env.engine.handle_button(env.user.id, question_button_id(t.result.needs_approval.id, 0))
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.COMPLETED and t.result.success
    booking_child = env.repos.tasks.items[t.result.details["booking_child_id"]]
    assert booking_child.type == TaskType.BOOKING and booking_child.status == S.COMPLETED
    assert env.runner.briefs[-1].approved_terms.startswith("Chill Point: Sun 10am")
    assert (S.AWAITING_CHOICE, S.WAITING_CHILDREN) in env.transitions
    assert (S.WAITING_CHILDREN, S.COMPLETED) in env.transitions


async def test_parallel_respects_concurrency(env):
    env.brain.fan_out = FanOutPolicy(strategy=FanOutStrategy.PARALLEL, concurrency=2)
    env.runner.gate = asyncio.Event()
    for p, amt in ((COOL, 699), (FROSTY, 599), (CHILL, 550)):
        env.runner.script(p, offer_then_confirm(p, amt))
    await env.repos.autonomy.upsert(AutonomySetting(user_id=env.user.id,
                                                    category=AutonomyCategory.BOOKINGS,
                                                    level=AutonomyLevel.ACT_WITH_APPROVAL))
    t = await env.engine.create_task(env.user.id, AC)
    for _ in range(50):
        await asyncio.sleep(0)
    assert env.runner.active == 2  # autonomy >= 3 skipped shortlist approval
    env.runner.gate.set()
    await env.engine.drain()
    t = await env.get(t.id)
    assert env.runner.max_active == 2 and t.status == S.AWAITING_CHOICE
    assert len(t.result.comparison.ranked_quotes) == 3


async def test_delegated_parent_auto_picks_and_books(env):
    for p, amt in ((COOL, 699), (FROSTY, 599), (CHILL, 550)):
        env.runner.script(p, offer_then_confirm(p, amt))
    spec = AC.model_copy(update={"delegation": Delegation(granted=True, max_price_inr=800)})
    await env.repos.autonomy.upsert(AutonomySetting(user_id=env.user.id,
                                                    category=AutonomyCategory.BOOKINGS,
                                                    level=AutonomyLevel.ACT_WITH_APPROVAL))
    t = await env.task(spec)
    assert t.status == S.COMPLETED
    kids = children(env, t.id)
    assert all(not k.delegation.granted for k in kids if role_of(k) == ROLE_FANOUT)
    booked = env.repos.tasks.items[t.result.details["booking_child_id"]]
    assert booked.delegation.granted and booked.target.phone == CHILL


async def test_stock_hunt_first_match_cancels_siblings(env):
    env.runner.gate = None
    slow = asyncio.Event()

    async def never(brief, ask, notify):
        await slow.wait()
        return result(brief, CallOutcome.DECLINED)

    async def has_it(brief, ask, notify):
        await asyncio.sleep(0.01)
        return result(brief, CallOutcome.SUCCESS, quotes=[quote("City Chemist", 30)],
                      collected={"summary": "City Chemist has Dolo 650"})

    env.runner.script("+912040000006", never)
    env.runner.script("+912040000007", has_it)
    spec = TaskSpec(type=TaskType.STOCK_HUNT, goal="Dolo 650 near Kothrud", item="Dolo 650",
                    discovery_query="chemist", location_text="Kothrud Pune")
    t = await env.task(spec)  # no shortlist approval for a stock hunt
    t = await env.get(t.id)
    assert t.status == S.COMPLETED and "Checked 2 places" in t.result.summary
    wellness = next(k for k in children(env, t.id) if k.target.phone == "+912040000006")
    assert wellness.status == S.CANCELLED
    assert env.runner.max_active == 2


async def test_stock_hunt_no_match_fails(env):
    env.runner.default = outcome(CallOutcome.DECLINED)
    spec = TaskSpec(type=TaskType.STOCK_HUNT, goal="Dolo", item="Dolo 650",
                    discovery_query="chemist", location_text="Kothrud Pune")
    t = await env.task(spec)
    assert t.status == S.FAILED and "None of the 2" in t.result.summary


async def test_no_offers_fails_with_outcomes(env):
    env.runner.default = outcome(CallOutcome.DECLINED)
    t = await env.task(AC)
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.FAILED and "couldn't get any offers" in t.result.summary


async def test_discovery_nothing_found(env):
    t = await env.task(AC.model_copy(update={"discovery_query": "yak grooming"}))
    assert t.status == S.FAILED


async def test_reject_shortlist_and_choice(env):
    t = await env.task(AC)
    await env.engine.approve(t.id, False)
    assert (await env.get(t.id)).status == S.CANCELLED
    for p, amt in ((COOL, 699), (FROSTY, 599), (CHILL, 550)):
        env.runner.script(p, offer_then_confirm(p, amt))
    t2 = await env.task(AC)
    await env.engine.approve(t2.id, True)
    await env.engine.drain()
    t2 = await env.get(t2.id)
    assert t2.status == S.AWAITING_CHOICE
    await env.engine.handle_button(env.user.id, question_button_id(t2.result.needs_approval.id, 2))
    await env.engine.drain()
    assert (await env.get(t2.id)).status == S.WAITING_CHILDREN  # 3 offers -> 3rd is a booking
    t3_cancel = await env.engine.cancel(t2.id)
    assert t3_cancel.status == S.CANCELLED


async def test_hotel_hybrid_with_api_offer_and_reconfirm(env):
    stay = StayRequest(destination="Udaipur", check_in=date(2026, 1, 20), check_out=date(2026, 1, 22),
                       max_rate_per_night_inr=4500)
    lake = "+912940000010"
    env.runner.script(lake, offer_then_confirm("Lakeview", 3800, ("deluxe lake view",)))
    env.runner.script("+912940000011", outcome(CallOutcome.NO_ANSWER))
    t = await env.task(TaskSpec(type=TaskType.HOTEL_BOOKING, goal="Stay in Udaipur for parents",
                                stay=stay))
    assert t.status == S.AWAITING_APPROVAL and t.result.hotel_offers
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.AWAITING_CHOICE
    lake_brief = next(b for b in env.runner.briefs if b.target.phone == lake)
    assert lake_brief.api_offer is not None and lake_brief.api_offer.rate_per_night_inr == 3220
    await env.engine.choose(t.id, 0)
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.COMPLETED
    booked = env.repos.tasks.items[t.result.details["booking_child_id"]]
    assert booked.type == TaskType.HOTEL_BOOKING and booked.result.hotel_booking is not None
    assert env.repos.tasks.hotel_bookings
    reconfirm = next(x for x in env.repos.tasks.items.values() if role_of(x) == ROLE_RECONFIRM)
    assert reconfirm.status == S.SCHEDULED and reconfirm.type == TaskType.RECONFIRM
    local = to_ist(reconfirm.next_attempt_at)
    assert local.date() == date(2026, 1, 19) and local.hour == 11
