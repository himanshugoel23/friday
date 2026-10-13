"""table_booking (pending v7, SCRIPTS_SPEC section 7a): hook, she states the request (no
availability question, no price), the nearest-slot rule, the delegated close, confirm mode."""

from __future__ import annotations

import asyncio

import pytest

from friday.playbooks.dryrun import PersonaDef, load_personas, run_persona
from friday.playbooks.model import PENDING_DIR, load_playbook

PB = load_playbook(PENDING_DIR / "table_booking.yaml")
PF = load_personas("table_booking", PENDING_DIR)
BASE = {p.id: p for p in PF.personas}

# A delegated table has no price: the engine's commit gate must not demand one (see the report:
# engine._can_commit + core.safety.check_commit need a "slot-only" decision for this archetype).
NEEDS_PRICE_FREE_COMMIT = pytest.mark.xfail(
    reason="engine: can_commit requires a price; a table has none", strict=False
)


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
    assert PB.archetype == "table_booking" and PB.ai_disclosure == "on_request"


def test_hook_then_the_request_is_stated_without_a_question_or_a_price():
    s = run("preview_available_no_delegation")
    spoken = friday(s)
    in_order(spoken, ["kya meri baat", "table booking ke regarding",
                      "hamko aaj shaam 7 baje ke liye 4 logon ka table"])
    joined = " ".join(spoken)
    assert "available hoga" not in joined and "price" not in joined and "charges" not in joined
    assert s.outcome == "AVAILABLE"
    assert "main ek baar Rahul sir ko bata deti hoon" in spoken[-1]


def test_resume_hook():
    s = run("resume_after_busy")
    assert "pehle table booking ke regarding" in " ".join(friday(s))


@NEEDS_PRICE_FREE_COMMIT
def test_delegated_close_names_the_user_and_the_time():
    s = run("preview_available_book")
    assert s.outcome == "BOOKED"
    last = friday(s)[-1]
    assert "4 logon ka table" in last and "ke naam se book kar lijiye" in last
    assert "main ek baar confirmation ke liye call kar lungi" in last


def test_not_available_follows_the_nearest_slot_rule_and_never_books():
    s = run("preview_not_available_nearest")
    spoken = friday(s)
    in_order(spoken, [
        "ke around ka slot available ho?", "sabse nearest kaun sa slot available hoga?",
        "confirm karke aapko thodi der mein call back",
    ])
    assert s.outcome == "SLOT_OFFERED"
    assert "book kar lijiye" not in " ".join(spoken)


def test_an_alternative_time_is_never_booked_even_with_a_delegation():
    s = run("not_available_alt_around")
    assert s.outcome == "SLOT_OFFERED"
    assert "book kar lijiye" not in " ".join(friday(s))


def test_nothing_free_ends_without_a_booking():
    s = run("not_available_nothing")
    assert s.outcome == "NO_SLOT" and "book kar lijiye" not in " ".join(friday(s))


def test_optional_extra_only_when_the_user_asked():
    asked = run("extras_asked")
    assert "window table ka bhi ho payega" in " ".join(friday(asked))
    plain = run("preview_available_no_delegation")
    assert "window" not in " ".join(friday(plain))


def test_booking_amount_raised_by_the_restaurant():
    s = run("advance_raised")
    assert s.outcome == "ADVANCE_ASKED"
    in_order(friday(s), [
        "advance ya booking amount kitna hoga", "advance payment initiate kar denge",
    ])


def test_whatsapp_number_is_read_back():
    s = run("whatsapp_digits_read_back")
    in_order(friday(s), ["ek baar aap please WhatsApp ka number", "yahi number hai na?",
                         "main aapko WhatsApp kar deti hoon"])


def test_confirm_mode_is_the_booking_close_behind_the_gate():
    s = run("confirm_callback")
    spoken = friday(s)
    assert "book kar lijiye" in spoken[-1] or "confirm karke" in spoken[-1]
    assert "available hoga" not in " ".join(spoken) and "S2" not in s.steps


def test_busy_asks_when_to_call_back():
    s = run("busy_callback")
    assert s.outcome == "CALL_BACK_LATER"
    assert "main kab call kar sakti hoon" in " ".join(friday(s))


@pytest.mark.parametrize("pid", ["ai_asked", "asks_otp", "puts_on_hold", "interrupted_asks_who"])
def test_interruptions_are_survived(pid):
    s = run(pid)
    assert not s.safety and s.outcome in ("BOOKED", "SLOT_OFFERED")
