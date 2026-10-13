"""salon_booking (pending v8): spoken order, confirm callback, resume, busy, advance rules."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from friday.playbooks import dryrun
from friday.playbooks.model import PENDING_DIR, load_playbook

PB = load_playbook(PENDING_DIR / "salon_booking.yaml")
PF = dryrun.load_personas("salon_booking", PENDING_DIR)


def _persona(**kw: Any) -> dryrun.PersonaDef:
    kw.setdefault("id", "t")
    kw.setdefault("greeting", "Hello, Looks Salon.")
    return dryrun.PersonaDef(**kw)


def _play(persona: dryrun.PersonaDef, **inputs: str) -> dryrun.RunScore:
    brief = dryrun.build_brief(PB, PF, persona)
    brief = brief.model_copy(update={"playbook_inputs": {**brief.playbook_inputs, **inputs}})

    async def go() -> dryrun.RunScore:
        return await dryrun.run_persona(PB, PF, persona, brief=brief)

    return asyncio.run(go())


def _said(score: dryrun.RunScore) -> list[str]:
    return [t for who, t in score.transcript if who.upper().startswith("FRIDAY")]


def _by_id(pid: str) -> dryrun.PersonaDef:
    return next(p for p in PF.personas if p.id == pid)


def test_happy_path_book_order():
    s = _play(_by_id("book_free_today"))
    said = _said(s)
    assert s.outcome == "BOOKED"
    assert said[0].startswith("Hello, kya meri baat")
    assert said[1].startswith("Ji sir, actually maine aapko")
    assert "ki booking ke regarding" in said[1]
    assert "estimated kya charges rahenge" in said[2]
    assert "ka slot booking ke liye aapke paas available hoga" in said[3]
    assert "book kar lijiye" in said[4] and "Thank you" in said[4]


def test_commit_blocked_when_a_different_time_was_offered():
    s = _play(_by_id("busy_slot_alt_not_booked"))
    assert s.outcome == "SLOT_OFFERED"
    assert not any("book kar lijiye" in t for t in _said(s))


def test_busy_asks_when_to_call_back():
    s = _play(_by_id("busy_after_hook"))
    assert s.outcome == "CALL_BACK_LATER"
    assert "main kab call kar sakti hoon" in _said(s)[-2]


def test_resume_uses_the_resume_hook_and_never_asks_the_price_again():
    s = _play(_by_id("resume_price_known_asks_nothing_again"))
    said = _said(s)
    assert "maine pehle" in said[1] and "ek-do cheezein reh gayi thi" in said[1]
    assert not any("estimated kya charges" in t for t in said)
    assert s.outcome == "QUOTE_COLLECTED"


def test_confirm_mode_books_what_the_user_approved():
    p = _persona(brief={"delegation_max_price": 800, "date_window": "aaj shaam 5 baje"},
                 replies={})
    s = _play(p, playbook_mode="confirm", resume="yes", prior_price_inr="400",
              prior_slot="aaj shaam 5 baje")
    said = _said(s)
    assert s.outcome == "BOOKED", said
    assert len(said) == 3  # identity question, hook, the booking line: nothing re-asked
    assert re.search(r"ne confirm kar diya hai, toh aap .*book kar lijiye", said[2])
    assert "5 baje" in said[2]


def test_business_raised_advance_is_asked_then_passed_on():
    s = _play(_by_id("quote_salon_raises_advance"))
    said = _said(s)
    assert s.outcome == "ADVANCE_ASKED"
    assert "ek baar advance ya booking amount kitna hoga" in said[-2]
    assert "advance payment initiate kar denge" in said[-1]
    assert not any("advance" in t for t in said[:3])


def test_advance_is_not_asked_on_her_own():
    s = _play(_by_id("advance_not_asked_by_default"))
    assert not any("amount" in t or "advance" in t for t in _said(s))
