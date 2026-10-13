"""cab_booking (pending): spoken order, toll only when not included, negotiation, confirm."""

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
    """The playbook, loaded with the engine fixes the report asks for (no-ops once applied): a
    digit in a placeholder name ({push2_price}), `prior_steps` keeping ">", the approved trip line
    ("cab book karani hai") and the WhatsApp-number sentence not read as booking claims."""
    import friday.voice.commit as vc

    mp = pytest.MonkeyPatch()
    ph = re.compile(r"\{([a-z0-9_]+)\}")

    def fill(template: str, value: Any) -> str:
        out = ph.sub(lambda m: value(m.group(1)), template)
        return out[:1].upper() + out[1:] if template.startswith("{") else out

    def rx(template: str) -> re.Pattern[str]:
        parts = re.split(r"\{[a-z0-9_]+\}", template)
        return re.compile("[^.!?]{1,90}?".join(re.escape(p) for p in parts), re.I)

    def exempt(fn):
        def inner(t):
            low = (t or "").lower()
            if "cab book karani hai" in low and "ne final confirm kar diya" not in low:
                return False
            if "whatsapp number confirm" in low:
                return False
            return fn(t)

        return inner

    mp.setattr(engine, "fill", fill)
    mp.setattr(engine, "_SAFE_INPUT", re.compile(r"[^\w\s'.\->]", re.U))
    mp.setattr(_model, "_PLACEHOLDER", ph)
    mp.setattr(dryrun.LineMatcher, "_rx", staticmethod(rx))
    mp.setattr(_model, "looks_like_commitment", exempt(_model.looks_like_commitment))
    mp.setattr(vc, "looks_like_commitment", exempt(vc.looks_like_commitment))
    mp.setattr(dryrun, "looks_like_commitment", vc.looks_like_commitment)
    pb = load_playbook(PENDING_DIR / "cab_booking.yaml")
    pf = dryrun.load_personas("cab_booking", PENDING_DIR)
    yield pb, pf
    mp.undo()


def _play(env, pid: str):
    pb, pf = env
    p = next(x for x in pf.personas if x.id == pid)
    return asyncio.run(dryrun.run_persona(pb, pf, p))


def _said(score) -> list[str]:
    return [t for who, t in score.transcript if who.upper().startswith("FRIDAY")]


def _in_order(said: list[str], parts: list[str]) -> None:
    joined = " || ".join(said)
    pos = 0
    for part in parts:
        i = joined.find(part, pos)
        assert i >= 0, f"{part!r} missing / out of order in {said}"
        pos = i


def test_happy_path_order_with_toll_not_included(env):
    s = _play(env, "preview_first_call")
    assert s.outcome == "QUOTE_COLLECTED"
    _in_order(_said(s), [
        "cab booking ke regarding call kiya tha",
        "Ji, hamko Noida se Jaipur jana hai, kal subah 6 baje ki cab book karani hai, "
        "hum 4 log hain.",
        "iska total estimated kitna charge rahega",
        "Aur kaun si gaadi milegi isme?",
        "sab kuch include rahega na? Toll, khana-peena, driver ka khana, charges wagairah?",
        "estimated kitna toll lagta hai isme",
        "kal subah 6 baje ke liye cab available hogi na?",
        "main ek baar Rahul sir ko bata deti hoon",
    ])


def test_toll_is_not_asked_when_everything_is_included(env):
    s = _play(env, "all_included")
    assert not any("toll lagta hai" in t for t in _said(s))


def test_the_trip_line_is_skipped_when_a_fact_is_missing(env):
    s = _play(env, "no_trip_facts")
    assert not any("jana hai" in t for t in _said(s))
    assert s.outcome == "QUOTE_COLLECTED"


def test_first_call_never_speaks_a_booking_line(env):
    for pid in ("preview_first_call", "other_time_offered", "not_available"):
        assert not any("kar lijiye" in t for t in _said(_play(env, pid))), pid


def test_resume_hook_and_answered_steps_are_not_asked_again(env):
    s = _play(env, "resume_after_inclusions")
    said = _said(s)
    assert "maine pehle" in said[1] and "ek-do cheezein reh gayi thi" in said[1]
    text = " ".join(said)
    for gone in ("total estimated", "kaun si gaadi", "sab kuch include"):
        assert gone not in text
    assert "cab available hogi na?" in text


def test_negotiation_never_exceeds_max_price(env):
    s = _play(env, "nego_push2_above_max")
    said = _said(s)
    assert s.outcome == "NEGOTIATION_FAILED"
    assert "Humara budget 10000 ka hai" in said[2]
    m = re.search(r"kya (\d+) tak ho payega", said[3])
    assert m and 10000 <= int(m.group(1)) <= 11000
    assert "final confirmation leke aapko call back karti hoon" in said[-1]
    assert max(int(n) for t in said for n in re.findall(r"\b\d{5}\b", t)) <= 11000


def test_negotiation_success_is_closed_with_the_usual_line(env):
    s = _play(env, "nego_push2_works")
    assert s.outcome == "PRICE_AGREED"
    assert "main ek baar Rahul sir ko bata deti hoon" in _said(s)[-1]


def test_confirm_mode_finalises_at_vendor_price_with_the_whatsapp_number(env):
    s = _play(env, "preview_callback_confirm")
    said = _said(s)
    assert s.outcome == "BOOKED", said
    assert "WhatsApp par pickup address share kar deti hoon" in said[2]
    assert said[3].endswith("yahi number hai na?")
    assert "hum 11000 pe final karte hain" in said[-1]
    assert "kal subah 6 baje ki booking aap Rahul ke naam se kar lijiye" in said[-1]


def test_confirm_line_is_blocked_without_a_known_pickup_slot(env):
    s = _play(env, "confirm_no_slot_known")
    assert s.outcome == "CONFIRM_PENDING"
    assert not any("kar lijiye" in t for t in _said(s))


def test_whatsapp_please_asks_for_the_number_and_reads_it_back(env):
    s = _play(env, "whatsapp_spoken_number")
    said = _said(s)
    assert s.outcome == "WHATSAPP_REQUESTED"
    assert said[-2].endswith("yahi number hai na?")
    assert said[-1] == "Okay sir, main aapko WhatsApp kar deti hoon."


def test_advance_only_when_the_business_raises_it(env):
    s = _play(env, "advance_raised_by_operator")
    assert s.outcome == "ADVANCE_ASKED"
    quiet = _play(env, "booking_amount_not_asked_by_default")
    assert not any("advance" in t or "booking amount" in t for t in _said(quiet))


def test_busy_asks_when_to_call_back(env):
    s = _play(env, "busy_callback")
    assert s.outcome == "CALL_BACK_LATER"
    assert "main kab call kar sakti hoon?" in _said(s)[-2]
