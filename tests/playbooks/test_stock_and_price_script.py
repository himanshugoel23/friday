"""stock_and_price (pending v7, SCRIPTS_SPEC section 6): the spoken order, the exchange answers,
resume, payment cases, negotiation ceiling and the hold line, driven through the real dry-run
machinery against simulated shops."""

from __future__ import annotations

import asyncio

import pytest

from friday.playbooks.dryrun import PersonaDef, load_personas, run_persona
from friday.playbooks.model import PENDING_DIR, load_playbook

PB = load_playbook(PENDING_DIR / "stock_and_price.yaml")
PF = load_personas("stock_and_price", PENDING_DIR)
BASE = {p.id: p for p in PF.personas}


def run(persona_id: str, *, brief: dict | None = None, replies: dict | None = None):
    base = BASE[persona_id]
    persona = PersonaDef(
        id=base.id, title=base.title, greeting=base.greeting,
        brief={**base.brief, **(brief or {})},
        replies={**base.replies, **(replies or {})},
        default=base.default, expect=base.expect, stop_request=base.stop_request,
    )
    return asyncio.run(run_persona(PB, PF, persona))


def friday(score) -> list[str]:
    return [t for who, t in score.transcript if who == "friday"]


def in_order(spoken: list[str], parts: list[str]) -> None:
    at = 0
    for part in parts:
        hits = [i for i in range(at, len(spoken)) if part in spoken[i]]
        assert hits, f"{part!r} not spoken (in order) in {spoken}"
        at = hits[0] + 1


def test_loads_and_is_an_archetype():
    assert PB.archetype == "stock_and_price" and PB.ai_disclosure == "on_request"


def test_happy_path_electronics_order():
    s = run("preview_electronics")
    assert s.outcome == "QUOTE_COLLECTED" and not s.safety
    in_order(friday(s), [
        "kya meri baat", "maine aapko", "available hoga", "estimated kya price rahega",
        "warranty kitni", "purana phone hai exchange", "exchange mein uska kitna milega",
        "ko bata deti hoon, aur thodi der mein aapko confirm karke batati hoon",
    ])


def test_not_in_stock_asks_when_it_arrives_and_never_a_price():
    s = run("preview_not_in_stock")
    assert s.outcome == "OUT_OF_STOCK"
    spoken = " ".join(friday(s))
    assert "kab tak aa jayega" in spoken and "estimated kya price" not in spoken


def test_exchange_questions_are_answered_from_the_facts_and_never_invented():
    s = run("exchange_asks_model")
    spoken = " ".join(friday(s))
    assert "iPhone 12" in spoken and "2021" in spoken
    missing = run("exchange_facts_missing")
    spoken = " ".join(friday(missing))
    assert "poochh kar bataungi" in spoken and "iPhone" not in spoken.replace("iphone", "")


def test_exchange_only_when_the_user_wants_it():
    s = run("no_exchange_asked")
    assert "exchange" not in " ".join(friday(s))


def test_florist_home_delivery_and_area_only_if_asked():
    s = run("preview_florist")
    spoken = friday(s)
    in_order(spoken, ["home delivery provide karte ho", "Indirapuram mein"])
    plain = run("preview_florist", replies={"s7d_ask": "Haan ho jayegi"})
    assert "Indirapuram" not in " ".join(friday(plain))


def test_resume_never_reasks_an_answered_question():
    s = run("resume_after_busy")
    spoken = " ".join(friday(s))
    assert "pehle" in spoken and "ek-do cheezein reh gayi thi" in spoken
    assert "available hoga" not in spoken and "estimated kya price" not in spoken
    assert "S2" not in s.steps and "S3" not in s.steps


def test_no_negotiation_for_electronics():
    s = run("preview_electronics")
    spoken = " ".join(friday(s))
    assert "budget" not in spoken and "N1" not in s.steps


def test_negotiation_never_goes_above_the_maximum():
    s = run("negotiate_florist_above_max")
    assert s.outcome == "NEGOTIATION_FAILED"
    asked = [t for t in friday(s) if "tak ho payega" in t]
    assert asked and "800 tak" in asked[0]
    assert "Humara budget 700 ka hai" in " ".join(friday(s))
    assert "final confirm" in friday(s)[-1]


def test_negotiation_agreed_at_target_stops_after_push_one():
    s = run("negotiate_florist_agrees_at_target")
    assert s.outcome == "NEGOTIATED" and "N2" not in s.steps


def test_confirm_mode_is_the_hold_line_and_needs_the_commit_gate():
    s = run("confirm_hold")
    assert s.outcome == "BOOKED"
    last = friday(s)[-1]
    assert "ne confirm kar diya hai" in last and "hold kar dijiye" in last
    blocked = run("confirm_hold", brief={"prior_slot": ""})
    assert blocked.outcome != "BOOKED"
    assert "hold kar dijiye" not in " ".join(friday(blocked))


def test_the_business_raises_a_booking_amount_upi_number_is_read_back():
    s = run("advance_raised")
    assert s.outcome == "PAYMENT_REQUESTED"
    in_order(friday(s), [
        "advance ya booking amount kitna hoga", "UPI number de dijiye",
        "9 8 1 1 1, 2 2 3 3 4, yahi number hai na?", "advance payment initiate kar denge",
    ])


def test_payment_by_whatsapp_qr_and_without_whatsapp():
    qr = run("advance_qr_by_whatsapp")
    assert qr.outcome == "PAYMENT_REQUESTED"
    in_order(friday(qr), ["isi number pe WhatsApp karna hai", "bank details bhej dijiye"])
    none = run("advance_no_whatsapp")
    assert none.outcome == "PAYMENT_REQUESTED"
    in_order(friday(none), [
        "isi number pe WhatsApp karna hai", "payment details yahin bata dijiye",
    ])


def test_booking_amount_is_asked_only_when_the_users_request_asks_it():
    asked = run("user_asks_booking_amount")
    assert "booking amount kitna lenge" in " ".join(friday(asked))
    plain = run("preview_electronics")
    assert "booking amount" not in " ".join(friday(plain))


def test_whatsapp_number_is_read_back_and_asked_again_when_wrong():
    s = run("whatsapp_digits_wrong_then_right")
    spoken = friday(s)
    assert sum("yahi number hai na?" in t for t in spoken) == 2
    assert "main aapko WhatsApp kar deti hoon" in spoken[-1]


def test_busy_asks_when_to_call_back():
    s = run("busy_callback")
    assert s.outcome == "CALL_BACK_LATER"
    assert "main kab call kar sakti hoon" in " ".join(friday(s))


@pytest.mark.parametrize("pid", ["ai_asked", "asks_otp", "asks_customer_phone", "puts_on_hold"])
def test_interruptions_do_not_lose_the_call(pid):
    s = run(pid)
    assert s.outcome == "QUOTE_COLLECTED" and not s.safety
