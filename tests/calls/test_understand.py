"""Request understander: deterministic first, one question at a time, never invents facts."""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.calls.fakes import FakeDraftLLM
from friday.calls.models import CalleeKind, PurposeKind
from friday.calls.understand import RequestUnderstander, parse_limits
from friday.core.clock import IST

U = RequestUnderstander()
NOW = datetime(2026, 1, 5, 11, 0, tzinfo=IST)


async def test_mummy_late():
    r = await U.understand("mummy ko phone karke bata do ki main late hoon", now=NOW)
    d = r.draft
    assert d.callee_kind == CalleeKind.FAMILY_FRIEND and d.callee_ref == "mummy"
    assert d.purpose == "main late hoon" and d.purpose_kind == PurposeKind.INFORM
    assert d.language == "hinglish" and r.ready and r.question_key is None


async def test_plumber_tomorrow_asks_limits():
    r = await U.understand("plumber ko call karo kal aane ke liye", now=NOW)
    d = r.draft
    assert d.callee_kind == CalleeKind.PROVIDER and d.callee_ref == "plumber"
    assert d.purpose == "kal aane ke liye" and d.purpose_kind == PurposeKind.REQUEST
    assert r.missing == ["limits"] and r.question_key == "ask_limits"


async def test_airtel_bill_dispute_asks_details_then_limits_one_at_a_time():
    r = await U.understand("Airtel customer care se bill dispute", now=NOW)
    d = r.draft
    assert d.callee_kind == CalleeKind.CUSTOMER_CARE and d.company == "Airtel"
    assert d.purpose_kind == PurposeKind.DISPUTE
    assert r.missing == ["details", "limits"]
    assert r.awaiting == "details" and r.question_key == "ask_details"  # exactly one question
    r2 = await U.understand("pichle mahine Rs 899 ka galat charge laga", prior=r, now=NOW)
    assert r2.draft.details and r2.draft.limits.max_price_inr == 899
    assert r2.ready  # amount given, nothing more to ask


async def test_school_fees():
    r = await U.understand("school office se fees ki date puchho", now=NOW)
    d = r.draft
    assert d.callee_kind == CalleeKind.OFFICIAL and d.purpose == "fees ki date puchho"
    assert d.purpose_kind == PurposeKind.ASK and r.ready


async def test_english_and_hindi():
    r = await U.understand("call my mom and tell her I'll be late", now=NOW)
    assert r.draft.callee_kind == CalleeKind.FAMILY_FRIEND and r.draft.language == "en"
    assert r.draft.purpose == "I'll be late"
    h = await U.understand("मम्मी को फोन करके बताओ कि मैं लेट हूँ", now=NOW)
    assert h.draft.callee_kind == CalleeKind.FAMILY_FRIEND and h.draft.language == "hindi"
    assert "लेट" in (h.draft.purpose or "")


async def test_vague_request_gets_one_question():
    r = await U.understand("Sharma ji ko call karo", now=NOW)
    assert r.missing == ["purpose"] and r.question_key == "ask_purpose"
    r = await U.understand("Sharma ji ko us baare mein call karo", now=NOW)
    assert "purpose" in r.missing  # "about that thing" is no purpose
    r = await U.understand("call karo", now=NOW)
    assert r.awaiting == "callee"


async def test_answer_fills_exactly_the_awaited_field():
    r = await U.understand("Sharma ji ko call karo", now=NOW)
    r2 = await U.understand("woh kal ki meeting ka time puchna hai", prior=r, now=NOW)
    assert r2.draft.callee_ref == "Sharma ji" and r2.draft.purpose
    assert r2.ready


async def test_bare_number_is_unknown_kind_and_not_invented():
    r = await U.understand("+91 90000 00001 ko call karke pucho kya cycle available hai", now=NOW)
    assert r.draft.number == "+919000000001" and r.draft.callee_kind == CalleeKind.UNKNOWN


async def test_group_with_names():
    r = await U.understand("sabko kal party ke liye call karo: Raj, Amit, Neha", now=NOW)
    assert r.draft.callee_kind == CalleeKind.GROUP
    assert r.draft.group_members == ["Raj", "Amit", "Neha"] and r.ready
    r = await U.understand("Raj, Amit aur Neha ko meeting ke liye call karo", now=NOW)
    assert r.draft.group_members == ["Raj", "Amit", "Neha"]


async def test_callback_of_missed_call():
    r = await U.understand("unka missed call aaya tha, call back karo", now=NOW)
    assert r.draft.callback_of == "missed:last" and r.draft.purpose_kind == PurposeKind.CALLBACK
    assert r.ready  # who and what come from the missed call


async def test_scheduled_time_only_when_unambiguous():
    r = await U.understand("mummy ko 5 pm pe call karke bata do ki main late hoon", now=NOW)
    assert r.draft.scheduled_for == datetime(2026, 1, 5, 17, 0, tzinfo=IST)
    r = await U.understand("mummy ko 5 baje call karke bata do ki main late hoon", now=NOW)
    assert r.draft.scheduled_for is None  # 5 baje: morning or evening? not guessed


def test_limits_parsing():
    now = NOW
    assert parse_limits("Rs 500 tak", now=now).max_price_inr == 500
    assert parse_limits("under 1,200 rupees", now=now).max_price_inr == 1200
    assert parse_limits("kal tak", now=now).deadline.date() == (now + timedelta(days=1)).date()
    assert parse_limits("kuch bhi", now=now).max_price_inr is None


async def test_unsafe_text_is_flagged_for_refusal():
    r = await U.understand("usko dhamki dene ke liye call karo", now=NOW)
    assert r.refusal_key == "refuse_threat"
    r = await U.understand("112 ko call karo", now=NOW)
    assert r.refusal_key == "refuse_emergency_number"
    ok = await U.understand("mummy ko call karke bata do ki main late hoon", now=NOW)
    assert ok.refusal_key is None


async def test_llm_proposal_is_used_only_when_grounded_in_the_message():
    llm = FakeDraftLLM({"callee_ref": "Sharma ji", "purpose": "kal ki meeting"})
    u = RequestUnderstander(llm)
    r = await u.understand("Sharma ji ko kal ki meeting ke baare mein phone lagao", now=NOW)
    assert llm.calls <= 1 and r.rejected_llm_fields == []


async def test_llm_cannot_invent_names_numbers_or_companies():
    llm = FakeDraftLLM(
        {
            "callee_ref": "Dr Gupta",  # not in the message
            "purpose": "refund of Rs 5000",  # amount not in the message
            "number": "+919111111111",  # not in the message
            "company": "HDFC",  # not in the message
            "callee_kind": "banana",
        }
    )
    u = RequestUnderstander(llm)
    r = await u.understand("kuch zaroori baat karni hai", now=NOW)
    d = r.draft
    assert d.callee_ref is None and d.number is None and d.company is None
    assert "5000" not in (d.purpose or "")
    assert set(r.rejected_llm_fields) >= {"callee_ref", "purpose", "number", "company"}
    assert "callee" in r.missing  # still asked, not guessed


async def test_llm_not_called_when_rules_are_enough():
    llm = FakeDraftLLM({"callee_ref": "x"})
    r = await RequestUnderstander(llm).understand(
        "mummy ko phone karke bata do ki main late hoon", now=NOW
    )
    assert llm.calls == 0 and r.ready
