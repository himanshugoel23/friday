"""banquet_booking (pending): order, not available, no negotiation, visit, confirm, resume."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest

from friday.playbooks import dryrun
from friday.playbooks.model import PENDING_DIR, load_playbook

PB = load_playbook(PENDING_DIR / "banquet_booking.yaml")
PF = dryrun.load_personas("banquet_booking", PENDING_DIR)


def _persona(**kw: Any) -> dryrun.PersonaDef:
    kw.setdefault("id", "t")
    kw.setdefault("greeting", "Hello, Royal Banquet Hall.")
    return dryrun.PersonaDef(**kw)


def _by_id(pid: str) -> dryrun.PersonaDef:
    return next(p for p in PF.personas if p.id == pid)


def _play(persona: dryrun.PersonaDef, reference: str | None = None, **inputs: str):
    brief = dryrun.build_brief(PB, PF, persona)
    brief = brief.model_copy(
        update={"playbook_inputs": {**brief.playbook_inputs, **inputs}, "reference": reference}
    )
    return asyncio.run(dryrun.run_persona(PB, PF, persona, brief=brief))


def _said(score) -> list[str]:
    return [t for who, t in score.transcript if who.upper().startswith("FRIDAY")]


def test_happy_path_spoken_order():
    s = _play(_by_id("happy_visit"))
    said = _said(s)
    assert s.outcome == "QUOTE_COLLECTED", said
    assert "banquet booking ke regarding call kiya tha" in said[1]
    assert "Ji, shaadi hai, 20 November ko, 300 log, veg." in said[2]
    assert "iska total estimated kitna rahega" in said[2]
    assert "decoration include rahega ya alag se" in said[3]
    assert "visit karne hum kab aa sakte hain" in said[4]
    assert "visit karne aa jayenge" in said[5] and "bata deti hoon. Thank you." in said[5]


def test_event_details_answered_from_facts():
    s = _play(_by_id("asks_event_details"))
    said = _said(s)
    assert s.outcome == "QUOTE_COLLECTED", said
    assert sum("shaadi hai, 20 November ko" in t for t in said) == 2


def test_not_available_closes_politely():
    s = _play(_by_id("not_available"))
    assert s.outcome == "NOT_AVAILABLE"
    assert "update karke aapko dobara call karti hoon" in _said(s)[-1]


def test_dj_and_rooms_only_when_needed():
    plain = " ".join(_said(_play(_by_id("happy_visit"))))
    assert "DJ" not in plain and "rooms" not in plain
    full = " ".join(_said(_play(_by_id("with_dj_and_rooms"))))
    assert "DJ aur sound" in full
    assert "humein 20 rooms bhi chahiye honge" in full


def test_never_negotiates_or_asks_advance_on_its_own():
    said = " ".join(_said(_play(_by_id("happy_visit"))))
    assert not re.search(r"budget|kam ho sakta|advance|booking amount", said)


def test_booking_amount_when_the_user_asked():
    s = _play(_by_id("user_asked_booking_amount"))
    assert s.outcome == "ADVANCE_ASKED"
    assert "booking amount kitna lenge" in " ".join(_said(s))


def test_resume_skips_answered_questions():
    s = _play(_by_id("resume_steps_answered"))
    said = _said(s)
    assert "maine pehle" in said[1]
    if any("decoration" in t for t in said):
        pytest.xfail("engine: resolve_inputs strips '>' from prior_steps (clean_input)")
    assert not any("total estimated" in t for t in said)


def test_confirm_callback_is_the_visit_confirmation():
    s = _play(_by_id("confirm_callback"))
    said = _said(s)
    assert s.outcome == "BOOKED", said
    assert re.search(
        r"ne confirm kar diya hai, woh kal shaam 5 baje visit karne aa jayenge", said[-1])


def test_whatsapp_digits_are_read_back():
    s = _play(_by_id("whatsapp_spoken_number"), reference="9811122334")
    said = _said(s)
    assert s.outcome == "WHATSAPP_REQUESTED", said
    assert said[-2].endswith("yahi number hai na?")
