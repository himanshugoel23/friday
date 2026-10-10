"""Founder rule: no commitment on the first call. Offer -> PENDING_APPROVAL -> the user
approves -> a CONFIRMATION call-back with the approved terms. Decline -> polite cancel."""

from __future__ import annotations

from friday.core.models import CallOutcome, TaskStatus, TaskType
from tests.e2e.harness import friday_lines

LOOKS = "+918040000001"
ASK = "Looks Unisex Salon mein haircut book karo kal shaam"


async def test_offer_waits_for_user_then_confirmation_callback(friday, rahul):
    await rahul.say(ASK)
    t = await rahul.task()
    assert t.type == TaskType.BOOKING and t.status == TaskStatus.AWAITING_APPROVAL
    calls = await rahul.calls(t)
    assert len(calls) == 1 and calls[0].outcome == CallOutcome.PENDING_APPROVAL
    assert calls[0].to_phone == LOOKS
    # the business was told Friday will call back, and nothing was committed
    said = " ".join(friday_lines(calls[0])).lower()
    # scripted salon call (friday/playbooks): one short close, "Theek hai, shukriya. Main ... se
    # poochh kar aapko batati hoon." - no recap, no confirmation (the LLM-driven policy said
    # "call back ... hold" instead)
    assert ("call back" in said and "hold" in said) or (
        "poochh kar aapko batati hoon" in said and "confirm" not in said
    )
    assert "committed" not in calls[0].collected
    assert t.approved_terms is None
    # the user sees the offer with tappable options (never an auto-booking)
    offer = rahul.last_msg()
    assert [b.title for b in offer.buttons][:2] == ["4 PM, ₹400", "6 PM, ₹400"]

    await rahul.say("2")  # tap "6 PM, ₹400"
    t = await rahul.task()
    assert t.status == TaskStatus.COMPLETED
    assert "6 PM" in (t.approved_terms or "")
    calls = await rahul.calls(t)
    assert [c.outcome for c in calls] == [CallOutcome.PENDING_APPROVAL, CallOutcome.SUCCESS]
    confirm = calls[1]
    assert confirm.collected.get("committed") == "true"
    assert "6 PM" in " ".join(friday_lines(confirm))  # the approved terms, not a new choice
    # sticky caller-ID: the same Friday number rings the same business back
    since = friday.clock.now().replace(year=2025)
    mem = await friday.c.repos.calls.recent_for_phone(LOOKS, since=since, limit=10)
    assert len(mem) == 2 and len({m.friday_number for m in mem}) == 1
    assert "Looks Unisex Salon" in rahul.last()


async def test_every_call_opens_with_the_ai_disclosure(friday, rahul):
    await rahul.say(ASK)
    await rahul.say("1")
    t = await rahul.task()
    calls = await rahul.calls(t)
    assert len(calls) == 2
    for c in calls:
        first = friday_lines(c)[0].lower()
        assert "ai assistant" in first and "friday" in first


async def test_declining_the_offer_cancels_politely(friday, rahul):
    await rahul.say(ASK)
    await rahul.say("3")  # "None of these"
    t = await rahul.task()
    assert t.status == TaskStatus.CANCELLED
    assert len(await rahul.calls(t)) == 1  # no confirmation call
    assert t.approved_terms is None
    # the business is released via the registered business-touch template, not a call
    touches = [m for m in friday.channel.messages_to(LOOKS)]
    assert touches and touches[-1].template is not None
    await friday.advance(hours=48)
    assert len(await rahul.calls(await rahul.task())) == 1


async def test_no_reply_means_no_booking(friday, rahul):
    await rahul.say(ASK)
    await friday.advance(hours=36)
    t = await rahul.task()
    assert t.status == TaskStatus.AWAITING_APPROVAL
    assert len(await rahul.calls(t)) == 1
    assert t.approved_terms is None


async def test_pre_call_approval_is_asked_when_autonomy_is_low(friday, rahul):
    """A stranger's number from discovery is never dialled before the user says Go."""
    await rahul.say("Indiranagar mein AC repair karne wala dhundo, 3 se quotes lo")
    t = await rahul.task()
    assert t.status == TaskStatus.AWAITING_APPROVAL
    assert not await rahul.calls(t)
    assert [b.title for b in rahul.last_msg().buttons][0].startswith("Call all")
