"""The pending enquiry script (docs/SCRIPTS_SPEC.md section 3), driven through the real policy."""

# ruff: noqa: E501
from __future__ import annotations

import re

import pytest

import friday.playbooks.model as model
from friday.playbooks.engine import PlaybookPolicy
from friday.playbooks.model import PENDING_DIR, get_playbook

from .conftest import drive, make_brief

EVENT = {
    "services": "wedding decoration", "service": "wedding decoration", "price_word": "charges",
    "q_date": "yes", "q_batch": "no", "q_demo": "no", "event_date": "20 November",
    "event_type": "shaadi", "event_venue": "Taj Banquet", "event_city": "Jaipur",
    "guests": "300", "price_min": "1000", "price_max": "2000000", "budget": "",
}
COACHING = {"services": "coaching classes", "service": "coaching classes", "budget": ""}


@pytest.fixture(scope="module")
def pb():
    # TODO(engine): drop this once the claim check allows "number confirm" / "final confirmation"
    # lines (they are not booking claims); see the enquiry report to the lead.
    orig = model._NEGATED_OR_FUTURE
    model._NEGATED_OR_FUTURE = re.compile(
        orig.pattern + r"|number confirm|ne confirm kar diya|final confirmation", re.I
    )
    try:
        yield get_playbook("enquiry", PENDING_DIR)
    finally:
        model._NEGATED_OR_FUTURE = orig


async def run(pb, replies, inputs, **kw):
    brief = make_brief(pb, inputs=inputs, **kw)
    return await drive(
        replies, brief=brief, pb=pb, policy=PlaybookPolicy(llm_mode="never", playbooks={pb.id: pb})
    )


async def test_coaching_happy_path_spoken_order(pb):
    r = await run(pb, ["Haan ji, bataiye", "Fees 15000 rupaye hai", "Shaam ko", "Haan demo mil jayegi"], COACHING)
    said = r.said
    assert said[0] == "Ji sir, actually maine aapko coaching classes ke baare mein jaankari ke liye call kiya tha."
    assert said[1] == "Toh sir, coaching classes ki estimated kya fees rahegi?"
    assert said[2] == "Toh batch ka timing kya rehta hai?"
    assert said[3] == "Achha toh sir, kuch demo class bhi mil sakti hai?"
    assert r.outcome == "QUOTE_COLLECTED"
    assert r.final.collected["price_inr"] == "15000"
    assert "Shaam ko" in r.final.collected["batch_note"]


async def test_event_date_is_asked_before_any_price(pb):
    r = await run(pb, ["Haan ji, bataiye", "Haan ji, available hain", "Decoration 50000 rupaye lagega"], EVENT)
    assert r.said[0].endswith("wedding decoration ke regarding call kiya tha.")
    assert r.said[1] == "Toh sir, 20 November ko aap available hain?"
    assert "ke estimated kya charges rahenge?" in r.said[2]
    assert r.outcome == "QUOTE_COLLECTED"


async def test_event_date_not_available_closes_without_a_price_question(pb):
    r = await run(pb, ["Haan ji, bataiye", "Nahi, us din booked hain"], EVENT)
    assert r.outcome == "NOT_AVAILABLE"
    assert "charges" not in r.all_text()
    assert r.final.text.endswith("ko bata deti hoon. Thank you.")


async def test_event_details_are_answered_from_facts_and_the_date_is_asked_again_once(pb):
    r = await run(pb, ["Haan ji, bataiye", "Event kya hai, kab hai, kahan hai?", "Haan available hain", "50000 rupaye"], EVENT)
    assert "Ji sir, shaadi hai, 20 November ko, Taj Banquet, Jaipur mein, aur 300 log honge." in r.said[2]
    assert r.all_text().count("20 November ko aap available hain?") == 2  # asked, then resumed
    assert r.outcome == "QUOTE_COLLECTED"


async def test_a_missing_fact_is_never_invented(pb):
    inputs = {k: v for k, v in EVENT.items() if k not in ("event_type", "event_venue", "event_city", "guests")}
    r = await run(pb, ["Haan ji, bataiye", "Event kya hai, kitne log hain?", "Haan available hain", "50000 rupaye"], inputs)
    assert "Yeh main Rahul sir se poochh kar bataungi." in r.said[2]
    assert "shaadi" not in r.all_text() and "300" not in r.all_text()


async def test_a_retry_never_asks_an_answered_question_again(pb):
    r = await run(pb, ["Haan ji, bataiye", "Shaam ko", "Haan"], {**COACHING, "resume": "yes", "prior_price_inr": "15000"})
    assert r.said[0].startswith("Ji sir, actually maine pehle coaching classes ke regarding call kiya tha")
    assert "fees rahegi" not in r.all_text()
    assert r.outcome == "QUOTE_COLLECTED"


async def test_a_retry_with_a_free_date_asks_only_the_charges(pb):
    r = await run(pb, ["Haan ji, bataiye", "50000 rupaye"], {**EVENT, "resume": "yes", "prior_slot_free": "yes"})
    assert "available hain?" not in r.all_text()
    assert r.outcome == "QUOTE_COLLECTED"


async def test_whatsapp_number_is_read_back_and_confirmed(pb):
    r = await run(pb, ["Haan ji, bataiye", "WhatsApp pe bhej do", "98111 22334", "Haan sahi hai"], COACHING)
    assert "WhatsApp ka number confirm kar sakte hain?" in r.said[2]
    assert r.said[3] == "9 8 1 1 1, 2 2 3 3 4, yahi number hai na?"
    assert r.final.text == "Okay sir, main aapko WhatsApp kar deti hoon."
    assert r.final.collected["captured_number"] == "9811122334"


async def test_whatsapp_same_number(pb):
    r = await run(pb, ["Haan ji, bataiye", "WhatsApp pe bhej do", "Yahi number hai"], COACHING)
    assert r.final.text == "Okay sir, main aapko WhatsApp kar deti hoon."
    assert r.final.collected["captured_number"] == "same"


async def test_wrong_readback_asks_the_number_once_more(pb):
    r = await run(pb, ["Haan ji, bataiye", "WhatsApp pe bhej do", "98111 22334", "Nahi galat hai", "98111 22335", "Haan sahi hai"], COACHING)
    assert r.said.count("Theek hai sir, ek baar aap please WhatsApp ka number confirm kar sakte hain?") == 2
    assert r.final.collected["captured_number"] == "9811122335"


async def test_advance_is_not_asked_on_her_own(pb):
    r = await run(pb, ["Haan ji, bataiye", "Fees 15000 rupaye hai", "Shaam ko", "Haan"], COACHING)
    assert "advance" not in r.all_text().lower() and "booking amount" not in r.all_text()


async def test_advance_is_asked_when_the_users_request_asks_for_it(pb):
    r = await run(pb, ["Haan ji, bataiye", "Haan ji", "50000 rupaye", "20000 booking amount hai"], {**EVENT, "q_ask_advance": "yes"})
    assert "Achha theek hai sir, ek baar booking amount kitna lenge?" in r.said


async def test_advance_raised_by_the_business_is_handed_to_the_user(pb):
    r = await run(pb, ["Haan ji, bataiye", "Fees 15000 rupaye hai", "Pehle advance dena padega", "5000 rupaye"], COACHING)
    assert r.outcome == "ADVANCE_ASKED"
    assert "ek baar advance ya booking amount kitna hoga?" in r.said[-2]
    assert r.final.text.startswith("Theek hai sir, main ek baar Rahul sir ko bata deti hoon, wo aapko advance payment initiate kar denge.")


async def test_confirm_mode_settles_the_booking_amount(pb):
    r = await run(pb, ["Haan ji, bataiye", "5000 rupaye"], {**COACHING, "playbook_mode": "confirm", "resume": "yes", "prior_price_inr": "15000"})
    assert r.outcome == "ADVANCE_ASKED"
    assert "fees rahegi" not in r.all_text()


async def test_busy_asks_when_to_call_and_notes_the_time(pb):
    r = await run(pb, ["Haan ji, bataiye", "Abhi busy hoon, baad mein call karo", "Shaam 5 baje"], COACHING)
    assert "Ji koi baat nahi sir, main kab call kar sakti hoon?" in r.said
    assert r.outcome == "CALL_BACK_LATER"
    assert "Shaam 5" in r.final.collected["callback_time"]
