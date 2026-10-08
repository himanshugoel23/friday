"""Customer-care IVR + hold + ticket + follow-up; hotel hybrid shortlist, booking, reconfirm."""

from __future__ import annotations

import pytest

from friday.core.models import CallOutcome, TaskStatus, TaskType
from tests.e2e.harness import callee_lines

CARE_ASK = "Airtel customer care ko call karo, mera broadband band hai, complaint darj karo"
HOTEL_ASK = "Udaipur mein Lake Pichola ke paas 2 raat ka homestay chahiye, 12 Feb se 14 Feb, 2 log"


async def _save_airtel_number(rahul):
    await rahul.say("my Airtel registered mobile number is 9876543210")
    await rahul.say("4826")  # saving an identifier needs the PIN
    assert "save kar liya" in rahul.last()


async def test_care_uses_the_official_number_and_never_shares_unapproved_details(friday, rahul):
    await _save_airtel_number(rahul)
    await rahul.say(CARE_ASK)
    t = await rahul.task()
    assert t.type == TaskType.CUSTOMER_CARE and t.status == TaskStatus.AWAITING_APPROVAL
    summary = rahul.last()
    assert "+911800000121" in summary and "official number" in summary
    assert "Never shared: OTPs, PINs, CVV, passwords." in summary
    await rahul.say("1")
    t = await rahul.task()
    (call,) = await rahul.calls(t)
    assert call.to_phone == "+911800000121"
    # the IVR asked for the registered number; nothing was approved, so nothing was typed
    assert call.outcome == CallOutcome.NEEDS_USER_VERIFICATION
    assert all("9876543210" not in x.text for x in call.transcript.turns)


async def test_care_ivr_hold_ticket_when_the_identifier_is_approved(friday, rahul):
    await _save_airtel_number(rahul)
    await rahul.say(CARE_ASK)
    t = await rahul.task()
    ids = await friday.c.repos.identifiers.list_for_user(t.requester_user_id)
    # (BUG-10b: nothing in the product approves a saved identifier yet; do it directly)
    await friday.engine.update_spec(
        t.id, t.spec.model_copy(update={"approved_identifier_ids": [i.id for i in ids]})
    )
    await rahul.say("1")
    t = await rahul.task()
    assert t.status == TaskStatus.COMPLETED
    (call,) = await rahul.calls(t)
    assert call.outcome == CallOutcome.SUCCESS and call.hold_seconds == 420
    assert call.care.ticket_number and call.care.ticket_number.startswith("SR")
    assert call.care.ivr_path[:2] == ["2", "3"]
    typed = [x.text for x in call.transcript.turns if x.text.startswith("DTMF")]
    assert any("3210#" in x for x in typed) and not any("9876" in x for x in typed)  # masked
    texts = rahul.texts()
    assert any("On hold with Airtel" in x for x in texts)  # hold progress, no LLM spend
    assert any(call.care.ticket_number in x for x in texts)


@pytest.mark.xfail(
    strict=True,
    reason="BUG-11: a ticket promised 'within 48 hours' is summarised as resolved=True, so the "
    "automatic follow-up (C25) is never scheduled although the user is told it will be",
)
async def test_care_follow_up_is_scheduled_for_the_promised_date(friday, rahul):
    await _save_airtel_number(rahul)
    await rahul.say(CARE_ASK)
    t = await rahul.task()
    ids = await friday.c.repos.identifiers.list_for_user(t.requester_user_id)
    await friday.engine.update_spec(
        t.id, t.spec.model_copy(update={"approved_identifier_ids": [i.id for i in ids]})
    )
    await rahul.say("1")
    follow = [x for x in await rahul.tasks() if x.parent_task_id == t.id]
    assert follow and follow[0].status == TaskStatus.SCHEDULED


async def test_otp_demanding_care_line_is_never_given_the_otp(friday, rahul):
    await rahul.say("Kaveri Bank card care ko call karo, card block karna hai")
    t = await rahul.task()
    if t.status == TaskStatus.AWAITING_APPROVAL:
        await rahul.say("1")
    calls = [c for tk in await rahul.tasks() for c in await rahul.calls(tk)]
    for c in calls:
        assert c.outcome != CallOutcome.SUCCESS
        keys = [x.text for x in c.transcript.turns if x.text.startswith("DTMF")]
        assert not any(k.rstrip("#")[-6:].isdigit() for k in keys), keys  # no OTP-like entry


async def test_hotel_hybrid_shortlist_booking_and_day_before_reconfirm(friday, rahul):
    await rahul.say(HOTEL_ASK)
    parent = await rahul.task()
    assert parent.type == TaskType.HOTEL_BOOKING and parent.status == TaskStatus.AWAITING_APPROVAL
    assert "Lakeview Homestay" in rahul.last() and "Old City Haveli Inn" in rahul.last()
    await rahul.say("1")
    parent = await rahul.task(0)
    assert parent.status == TaskStatus.AWAITING_CHOICE
    assert "₹4,200 → ₹2,800" in rahul.last()  # direct (negotiated) rate vs listed rate
    assert not [t for t in await rahul.tasks() if t.status == TaskStatus.CALLING]
    await rahul.say("1")  # pick Lakeview
    reconf = next(t for t in await rahul.tasks() if t.type == TaskType.RECONFIRM)
    assert reconf.status == TaskStatus.SCHEDULED
    assert reconf.next_attempt_at.date().isoformat() == "2026-02-11"  # the day before check-in
    assert "Ho gaya" in rahul.last()


@pytest.mark.xfail(
    strict=True,
    reason="BUG-12: the day-before reconfirm call quotes dates/reference as long digit strings, "
    "the unapproved-number guard blocks it and the user is bridged into every reconfirm",
)
async def test_hotel_reconfirm_completes_without_pulling_the_user_in(friday, rahul):
    await rahul.say(HOTEL_ASK)
    await rahul.say("1")
    await rahul.say("1")
    await friday.advance(days=37, hours=5)
    reconf = next(t for t in await rahul.tasks() if t.type == TaskType.RECONFIRM)
    (call,) = await rahul.calls(reconf)
    assert call.outcome == CallOutcome.SUCCESS
    assert callee_lines(call)
