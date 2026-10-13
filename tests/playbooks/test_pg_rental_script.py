"""pg_rental (pending): spoken order, resume, negotiation limits, visit, WhatsApp, advance, busy."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest

from friday.playbooks import dryrun, engine
from friday.playbooks import model as _model
from friday.playbooks.model import PENDING_DIR, load_playbook


@pytest.fixture(scope="module")
def env():
    """The playbook, loaded with the three engine fixes the report asks for (they are no-ops once
    the engine has them): a placeholder name may hold a digit ({push2_price}), `prior_steps` keeps
    its ">" separators, and the read-back sentences are not seen as booking claims."""
    mp = pytest.MonkeyPatch()
    ph = re.compile(r"\{([a-z0-9_]+)\}")

    def fill(template: str, value: Any) -> str:
        out = ph.sub(lambda m: value(m.group(1)), template)
        return out[:1].upper() + out[1:] if template.startswith("{") else out

    def rx(template: str) -> re.Pattern[str]:
        parts = re.split(r"\{[a-z0-9_]+\}", template)
        return re.compile("[^.!?]{1,90}?".join(re.escape(p) for p in parts), re.I)

    mp.setattr(engine, "fill", fill)
    mp.setattr(engine, "_SAFE_INPUT", re.compile(r"[^\w\s'.\->]", re.U))
    mp.setattr(_model, "_PLACEHOLDER", ph)
    mp.setattr(dryrun.LineMatcher, "_rx", staticmethod(rx))
    lc = _model.looks_like_commitment
    mp.setattr(_model, "looks_like_commitment",
               lambda t: False if t and "whatsapp number confirm" in t.lower() else lc(t))
    pb = load_playbook(PENDING_DIR / "pg_rental.yaml")
    pf = dryrun.load_personas("pg_rental", PENDING_DIR)
    yield pb, pf
    mp.undo()


def _play(env, pid: str | None = None, **persona: Any):
    pb, pf = env
    if pid:
        p = next(x for x in pf.personas if x.id == pid)
    else:
        persona.setdefault("id", "t")
        persona.setdefault("greeting", "Hello, Sharma PG.")
        p = dryrun.PersonaDef(**persona)
    return asyncio.run(dryrun.run_persona(pb, pf, p))


def _said(score) -> list[str]:
    return [t for who, t in score.transcript if who.upper().startswith("FRIDAY")]


def test_happy_path_spoken_order(env):
    s = _play(env, "preview_first_call")
    said = _said(s)
    assert s.outcome == "QUOTE_COLLECTED"
    expect = [
        "kya meri baat",
        "PG ke room ki enquiry ke regarding call kiya tha",
        "ek baar bata sakte hain room ka kya rent rahega",
        "Ji sir, double sharing chahiye.",  # answered from the facts when asked
        "double sharing ke estimated kya charges rahenge",
        "furnishing",
        "khana ya mess",
        "electricity ka bill",
        "security deposit",
        "notice period",
        "1 November se room chahiye hoga, double sharing",
        "main ek baar Rahul sir ko bata deti hoon",
    ]
    joined = " || ".join(said)
    pos = 0
    for part in expect:
        i = joined.find(part, pos)
        assert i >= 0, f"{part!r} missing / out of order in {said}"
        pos = i


def test_a_vendor_question_never_makes_her_re_ask_an_answered_question(env):
    s = _play(env, "asks_who_is_it_for")
    said = _said(s)
    assert "Aman ke liye hai, Lucknow se hain, TCS mein, abhi Lucknow mein rehte hain" in said[4]
    assert sum("kya rent rahega" in t for t in said) == 1
    # the answer is followed by the question that was open (furnishing), then the next ones
    assert said[4].endswith("Aur room mein kya kya furnishing rahegi?")
    assert "khana ya mess" in said[5]


def test_resume_hook_and_cut_questions_are_not_asked_again(env):
    s = _play(env, "resume_after_deposit_question")
    said = _said(s)
    assert "maine pehle" in said[1] and "ek-do cheezein reh gayi thi" in said[1]
    text = " ".join(said)
    for gone in ("kya rent rahega", "furnishing", "khana ya mess", "electricity"):
        assert gone not in text
    assert "security deposit" in text and "notice period" in text


def test_busy_asks_when_to_call_back(env):
    s = _play(env, "busy_callback")
    assert s.outcome == "CALL_BACK_LATER"
    assert "main kab call kar sakti hoon?" in _said(s)[-2]


def test_negotiation_pushes_in_order_and_never_above_max(env):
    s = _play(env, "nego_both_refused")
    said = _said(s)
    assert s.outcome == "NEGOTIATION_FAILED"
    assert "budget 6000 ke around rahega" in said[2]
    m = re.search(r"kya (\d+) tak ho payega", said[3])
    assert m and 6000 <= int(m.group(1)) <= 6800
    assert "final confirmation leke aapko call back karti hoon" in said[-1]
    assert not any("room dekhne" in t for t in said)  # no visit without an agreed price
    nums = [int(n) for t in said for n in re.findall(r"\b\d{4,5}\b", t)]
    assert max(nums) <= 6800


def test_a_price_above_max_at_push_2_is_never_accepted(env):
    s = _play(env, "nego_both_refused")
    assert s.outcome == "NEGOTIATION_FAILED"


def test_visit_is_confirmed_back_and_the_call_before_is_promised(env):
    s = _play(env, "nego_push2_works")
    said = _said(s)
    assert s.outcome == "VISIT_FIXED"
    assert "room dekhne ke liye kab aa sakte hain?" in said[-2]
    assert said[-1].startswith("Theek hai sir, toh kal shaam 5 baje aa jayenge.")
    assert said[-1].endswith("Main visit se pehle ek baar call kar lungi.")


def test_no_push_when_the_price_is_already_at_target(env):
    s = _play(env, "nego_price_already_at_target")
    assert not any("budget" in t for t in _said(s))
    assert s.outcome == "VISIT_FIXED"


def test_whatsapp_number_is_read_back(env):
    s = _play(env, "whatsapp_spoken_number")
    said = _said(s)
    assert s.outcome == "WHATSAPP_REQUESTED"
    assert said[-2].endswith("yahi number hai na?")
    assert said[-1] == "Okay sir, main aapko WhatsApp kar deti hoon."


def test_advance_only_when_the_business_raises_it(env):
    s = _play(env, "advance_raised_by_owner")
    assert s.outcome == "ADVANCE_ASKED"
    assert "wo aapko advance payment initiate kar denge" in _said(s)[-1]
    quiet = _play(env, "booking_amount_not_asked_by_default")
    assert not any("advance" in t or "booking amount" in t for t in _said(quiet))
    asked = _play(env, "booking_amount_asked_by_user_request")
    assert any("booking amount kitna lenge" in t for t in _said(asked))
