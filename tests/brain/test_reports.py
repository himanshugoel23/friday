"""AI-7 summarize_call / compare_quotes, AI-8 shortlist, E-36 retry copy."""

from __future__ import annotations

from datetime import date, timedelta

from friday.core.models import (
    Beneficiary,
    Budget,
    BusinessCandidate,
    CallOutcome,
    CallResult,
    CareOutcome,
    ContactTarget,
    DialStatus,
    GeoPoint,
    InteractionKind,
    Language,
    Quote,
    Speaker,
    TargetKind,
    Task,
    TaskSpec,
    TaskType,
    Tone,
    Transcript,
    VendorInteraction,
)
from friday.simworld import load_world

from .conftest import NOW, make_ctx


def _task(ttype=TaskType.BOOKING, **kw) -> Task:
    spec = TaskSpec(type=ttype, goal=kw.pop("goal", "Book a haircut"),
                    business_name="Looks Salon", business_phone="+918040000001",
                    item=kw.pop("item", None))
    return Task(id="t1", requester_user_id="u1", type=ttype, spec=spec,
                target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks Salon",
                                     phone="+918040000001", business_id="b_looks"), **kw)


def _result(outcome, **kw) -> CallResult:
    data = dict(task_id="t1", provider="simulator", to_phone="+918040000001",
                dial_status=DialStatus.ANSWERED, outcome=outcome, started_at=NOW)
    data.update(kw)
    return CallResult(**data)


async def test_success_booking(brain, ctx):
    r = _result(CallOutcome.SUCCESS, collected={"confirmed_terms": "Sat 12:30 PM, ₹600"},
                quotes=[Quote(business_name="Looks Salon", amount_inr=600, price_text="₹600",
                              available_slots=["Sat 12:30 PM"])],
                languages_heard=[Language.KN])
    res = await brain.summarize_call(ctx, _task(), r)
    assert res.success and "Looks Salon" in res.summary and "12:30" in res.summary
    assert res.appointment_at is not None and res.appointment_at.date() == date(2026, 10, 10)
    kinds = {i.kind for i in res.interactions}
    assert {InteractionKind.CALLED, InteractionKind.QUOTED, InteractionKind.BOOKED} <= kinds
    assert res.business_touch.key == "business_booking_confirmed"
    assert any(f.key == "business_language" and f.value == "kn" for f in res.facts)


async def test_pending_approval_produces_question(brain, ctx):
    r = _result(CallOutcome.PENDING_APPROVAL, collected={"held": "yes"},
                quotes=[Quote(business_name="Looks Salon", amount_inr=600, price_text="₹600",
                              available_slots=["10 AM", "12:30 PM"])])
    res = await brain.summarize_call(ctx, _task(), r)
    assert not res.success and res.needs_approval is not None
    q = res.needs_approval
    assert q.purpose.value == "approve_booking" and q.options[-1] == "None of these"
    assert len(q.options) == 3 and "12:30 PM, ₹600" in q.options


async def test_busy_first_attempt_keeps_trying_copy(brain, ctx):
    task = _task(attempts=1, max_attempts=3)
    res = await brain.summarize_call(ctx, task, _result(CallOutcome.BUSY,
                                                        dial_status=DialStatus.BUSY))
    assert "keep trying" in res.summary or "try karti rahungi" in res.summary
    nxt = res.details["next_attempt_at"]
    assert nxt.startswith("2026-10-07T04:35")  # busy -> +5 min (10:05 IST)
    assert res.retry_suggested


async def test_no_answer_uses_engine_next_attempt(brain):
    ctx = make_ctx(language=Language.EN)
    task = _task(attempts=2, max_attempts=3, next_attempt_at=NOW + timedelta(minutes=45))
    res = await brain.summarize_call(ctx, task, _result(CallOutcome.NO_ANSWER,
                                                        dial_status=DialStatus.NO_ANSWER))
    assert "isn't picking up" in res.summary and "10:45 am" in res.summary


async def test_final_no_answer_report_with_options(brain):
    ctx = make_ctx(language=Language.EN)
    task = _task(attempts=3, max_attempts=3)
    res = await brain.summarize_call(ctx, task, _result(CallOutcome.NO_ANSWER,
                                                        dial_status=DialStatus.NO_ANSWER))
    assert "Couldn't reach Looks Salon after 3 tries" in res.summary
    assert res.next_steps == ["Try later today", "Try tomorrow", "Pick another business"]


async def test_declined_and_refused_ai(brain, ctx):
    res = await brain.summarize_call(ctx, _task(), _result(CallOutcome.DECLINED,
                                                           collected={"refused_ai": "true"}))
    assert "AI" in res.summary and not res.success


async def test_care_ticket_follow_up(brain, ctx):
    care = CareOutcome(company="Airtel", ticket_number="SR581239",
                       promised_date=date(2026, 10, 20), promised_text="by 20 Oct")
    task = _task(TaskType.CUSTOMER_CARE, goal="Refund")
    res = await brain.summarize_call(ctx, task, _result(CallOutcome.SUCCESS, care=care))
    assert "SR581239" in res.summary and res.care.ticket_number == "SR581239"
    assert res.follow_up_at.date() == date(2026, 10, 21)  # promised date + 24h grace


async def test_wellbeing_alert(brain, family_ctx):
    task = Task(id="tw", requester_user_id="u1", type=TaskType.WELLBEING_CHECKIN,
                beneficiary=Beneficiary(person_id="p_dad"),
                spec=TaskSpec(type=TaskType.WELLBEING_CHECKIN, goal="check in"))
    tr = Transcript()
    tr.add(Speaker.CALLEE, "Subah se chakkar aa raha hai, dawai nahi li")
    res = await brain.summarize_call(family_ctx, task, _result(
        CallOutcome.SUCCESS, transcript=tr, collected={"medicine_taken": "no"}))
    assert res.alert and "chakkar" in res.alert and "Suresh" in res.summary
    assert res.business_touch is None


async def test_tone_changes_copy(brain):
    r = _result(CallOutcome.SUCCESS, collected={"confirmed_terms": "Sat 12:30 PM"})
    formal = await brain.summarize_call(make_ctx(language=Language.EN, tone=Tone.FORMAL),
                                        _task(), r)
    playful = await brain.summarize_call(make_ctx(language=Language.EN, tone=Tone.PLAYFUL),
                                         _task(), r)
    assert formal.summary != playful.summary and "✅" not in formal.summary


async def test_routine_outcomes_use_no_llm(brain, fake_llm, ctx):
    await brain.summarize_call(ctx, _task(attempts=1), _result(CallOutcome.BUSY))
    assert not fake_llm.calls_for("summarize")
    await brain.summarize_call(ctx, _task(), _result(CallOutcome.SUCCESS))
    assert fake_llm.calls_for("summarize")[-1].model == "claude-haiku-5-5"


async def test_compare_quotes_ranking_and_buttons(brain):
    parent = Task(id="p1", requester_user_id="u1", type=TaskType.DISCOVERY,
                  spec=TaskSpec(type=TaskType.DISCOVERY, goal="AC repair",
                                budget=Budget(max_inr=800)))
    quotes = [Quote(business_name="Pricey AC", amount_inr=1200, price_text="₹1200"),
              Quote(business_name="CoolCare", amount_inr=600, original_amount_inr=699,
                    price_text="₹699 -> ₹600", available_slots=["Sat 11 AM"]),
              Quote(business_name="Chill Point", amount_inr=550, price_text="₹550")]
    cmp = await brain.compare_quotes(make_ctx(language=Language.EN), parent, quotes)
    assert [q.business_name for q in cmp.ranked_quotes] == ["Chill Point", "CoolCare",
                                                            "Pricey AC"]
    assert cmp.recommended_index == 0 and "₹699 → ₹600" in cmp.summary
    assert [b.id for b in cmp.buttons] == ["c:p1:0", "c:p1:1", "c:p1:none"]
    assert all(len(b.title) <= 20 for b in cmp.buttons)


def _ac_candidates() -> list[BusinessCandidate]:
    world = load_world()
    out = []
    for b in world.businesses:
        if b.category == "ac repair":
            out.append(BusinessCandidate(provider="simulator", place_id=b.id, name=b.name,
                                         phone=b.phone, rating=b.rating,
                                         review_count=b.review_count,
                                         review_snippets=[r.text for r in b.reviews],
                                         location=GeoPoint(lat=b.lat, lng=b.lng)))
    out.append(BusinessCandidate(provider="simulator", place_id="nophone", name="No Phone AC",
                                 rating=5.0, review_count=999))
    return out


async def test_shortlist_deterministic_on_simworld_ac_set(brain, ctx):
    spec = TaskSpec(type=TaskType.DISCOVERY, goal="AC repair", discovery_query="ac repair")
    a = await brain.shortlist(ctx, spec, _ac_candidates(), 3)
    b = await brain.shortlist(ctx, spec, list(reversed(_ac_candidates())), 3)
    assert [i.candidate.name for i in a] == [i.candidate.name for i in b]
    assert a[0].candidate.name == "CoolCare AC Services"
    assert "No Phone AC" not in [i.candidate.name for i in a]
    assert [i.rank for i in a] == [1, 2, 3] and "4.7★" in a[0].reason


async def test_shortlist_vendor_history_and_reason_batch(brain, fake_llm):
    ctx = make_ctx(known_businesses=[], vendor_history=[])
    from friday.core.models import Business

    ctx = make_ctx(known_businesses=[Business(id="bf", name="Frosty Air Solutions",
                                              phone="+918040000004")],
                   vendor_history=[VendorInteraction(user_id="u1", business_id="bf",
                                                     kind=InteractionKind.NO_SHOW)])
    spec = TaskSpec(type=TaskType.DISCOVERY, goal="AC", discovery_query="ac repair")
    items = await brain.shortlist(ctx, spec, _ac_candidates(), 3)
    assert items[-1].candidate.name == "Frosty Air Solutions"
    assert "bad experience" in items[-1].reason
    assert len(fake_llm.calls_for("shortlist_reasons")) == 1  # one batched call


async def test_llm_reason_with_phone_number_is_rejected(brain, fake_llm, ctx):
    fake_llm.script("shortlist_reasons", {"reasons": [
        {"index": 0, "reason": "Call 98450 12345 now, best!"}]})
    spec = TaskSpec(type=TaskType.DISCOVERY, goal="AC", discovery_query="ac repair")
    items = await brain.shortlist(ctx, spec, _ac_candidates(), 2)
    assert "98450" not in items[0].reason
