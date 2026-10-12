# ruff: noqa: E501
"""Anti-hallucination and anti-repetition: nothing the vendor did not say survives, and Friday never
says the same line again and again (script engine, LLM-written lines, duplicate speech results)."""

from __future__ import annotations

import pytest

from friday.playbooks.engine import PlaybookPolicy
from friday.playbooks.understand import Understanding, ground

from .conftest import drive, make_brief


# ------------------------------------------------------------------ grounding of model output
@pytest.mark.parametrize(("reply", "claimed", "kept"), [
    ("haircut 300 ka hai", 300, True),
    ("teen sau rupaye lagenge", 300, True),
    ("dhai sau", 250, True),
    ("paanch sau se saat sau tak", 500, True),
    ("kam se kam 5k", 5000, True),
    ("haircut 300 ka hai", 500, False),               # the model invented 500
    ("pata nahi, aake dekh lijiye", 400, False),      # no number was said at all
])
def test_a_price_is_kept_only_if_the_vendor_said_it(reply, claimed, kept):
    u = ground(Understanding(intent="GIVES_PRICE", price_inr=claimed), reply)
    assert (u.price_inr == claimed) is kept


def test_range_low_deposit_duration_and_stylist_are_checked_too():
    u = Understanding(intent="PRICE_RANGE", price_inr=500, price_low_inr=300, deposit_inr=100,
                      duration_min=45, stylist="Meena")
    g = ground(u, "300 se 500 tak, aadha ghanta lagta hai")
    assert (g.price_inr, g.price_low_inr) == (500, 300)
    assert g.deposit_inr is None and g.duration_min is None and g.stylist is None


def test_times_must_be_in_the_words_but_spoken_hours_count():
    ok = ground(Understanding(intent="GIVES_TIME", time="shaam 6 baje"), "bas shaam chhe")
    assert ok.time == "shaam 6 baje"
    ok2 = ground(Understanding(intent="OFFERS_SLOTS", time="shaam 6 baje", alt_times=["shaam 7 baje"]),
                 "6 baje ya 7 baje aa jaiye")
    assert ok2.time == "shaam 6 baje" and ok2.alt_times == ["shaam 7 baje"]
    bad = ground(Understanding(intent="OFFERS_SLOTS", time="shaam 6 baje", alt_times=["shaam 8 baje"]),
                 "6 baje free hai")
    assert bad.time == "shaam 6 baje" and bad.alt_times == []
    gone = ground(Understanding(intent="SLOT_FREE", time="shaam 5 baje"), "haan ho jayega")
    assert gone.time is None


async def test_a_model_that_invents_a_price_makes_friday_ask_again_not_record_it():
    class Liar:
        async def understand(self, *, reply, step, **kw):
            if step == "S3":
                return Understanding(intent="GIVES_PRICE", price_inr=450)  # vendor said no number
            from friday.playbooks.understand import heuristic

            return heuristic(reply, step=step)

    policy = PlaybookPolicy(understander=Liar(), llm_mode="always")
    run = await drive(["achha, dekhte hain"], policy=policy, brief=make_brief())
    assert run.state.price_inr is None  # nothing was recorded
    assert "ke kya charges rahenge" in run.all_text()  # she simply asked again


# ------------------------------------------------------------------ never the same line again and again
async def test_a_vendor_who_keeps_saying_haan_does_not_get_the_same_question_forever():
    run = await drive(["Haan ji"] * 8, brief=make_brief())
    same = [t for t in run.said if "ke kya charges rahenge" in t]
    assert len(same) <= 3
    assert run.final.type.value == "hangup"  # it ended politely instead of looping


async def test_one_repeat_is_allowed_when_asked():
    run = await drive(["Sorry, phir se boliye?", "400 rupaye"], brief=make_brief())
    assert run.outcome == "QUOTE_COLLECTED"


# ------------------------------------------------------------------ LLM-written lines
def _guard(text, *, transcript_lines=(), brief=None):
    from friday.brain import guards
    from friday.brain.schemas import CallActionOut
    from friday.core.models import CallActionType, Language, Speaker, Transcript

    from .conftest import make_brief as mk

    brief = brief or mk()
    tr = Transcript()
    for speaker, t in transcript_lines:
        tr.add(Speaker.FRIDAY if speaker == "f" else Speaker.CALLEE, t)
    out = CallActionOut(type=CallActionType.SAY, text=text, language=Language.HINGLISH)
    return guards.to_call_action(out, brief, [], tr)


def test_llm_line_with_a_made_up_price_or_time_is_replaced():
    from friday.core.models import CallActionType

    a = _guard("Toh haircut ke 750 rupaye lagenge na?", transcript_lines=[("c", "haircut chahiye?")])
    assert a.type != CallActionType.SAY or "750" not in (a.text or "")
    assert "ungrounded" in a.collected.get("guard", "")
    b = _guard("Toh kal shaam 9 baje aa jayenge na?", transcript_lines=[("c", "kal aa jaiye")])
    assert "ungrounded" in b.collected.get("guard", "")


def test_llm_line_repeating_a_number_the_vendor_said_is_fine():
    a = _guard("Theek hai, 400 rupaye.", transcript_lines=[("c", "haircut 400 rupaye ka hai")])
    assert a.text == "Theek hai, 400 rupaye." and "guard" not in a.collected


def test_llm_repeating_itself_ends_the_call_politely():
    lines = [("f", "Kya aap ka slot khaali hai?"), ("c", "hmm"), ("f", "Kya aap ka slot khaali hai?"),
             ("c", "haan?")]
    a = _guard("Kya aap ka slot khaali hai?", transcript_lines=lines)
    assert a.type.value == "hangup" and a.collected.get("guard") == "repeating_herself"
