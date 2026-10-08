"""Regression tests for the QA brain/voice bugs (docs/QA_REPORT.md BUG-1/4/8/9/15/17)."""

from __future__ import annotations

from friday.brain.heuristics.references import resolve
from friday.brain.textutil import extract_amounts
from friday.core.models import (
    CallActionType,
    CallOutcome,
    Delegation,
    GeoPoint,
    Place,
    TaskType,
)

from .conftest import business_brief, make_ctx
from .test_policy import play


def _stock_brief():
    return business_brief(task_type=TaskType.STOCK_HUNT, goal="Find Dolo 650",
                          questions=["Do you have Dolo 650 in stock?"])


async def test_bug8_repeat_request_is_not_in_stock(brain):
    actions, _ = await play(brain, _stock_brief(), ["Sorry, phir se boliye?"] * 2)
    last = actions[-1]
    assert last.outcome == CallOutcome.PARTIAL
    assert last.collected["in_stock"] == "unknown"
    assert sum("phir se" in (a.text or "") for a in actions) == 1  # asked again once


async def test_bug8_affirmative_in_hinglish_and_hindi_is_in_stock(brain):
    for line in ("Haan ji, Dolo 650 available hai.", "हाँ जी, उपलब्ध है।", "Yes we have it"):
        actions, _ = await play(brain, _stock_brief(), [line])
        assert actions[-1].outcome == CallOutcome.SUCCESS, line
        assert actions[-1].collected["in_stock"] == "yes"


async def test_bug8_negative_is_declined(brain):
    actions, _ = await play(brain, _stock_brief(), ["माफ़ कीजिए, अभी स्टॉक में नहीं है।"])
    assert actions[-1].outcome == CallOutcome.DECLINED


async def test_bug1_delegated_confirmation_sets_slot_at(brain):
    d = Delegation(granted=True, max_price_inr=1000, time_window_text="5 PM-7 PM",
                   user_words="any slot 5-7 under 1000, you decide")
    brief = business_brief(task_type=TaskType.HEALTHCARE, delegation=d)
    actions, _ = await play(brain, brief, ["Thursday 5:30 pm hai, 800 rupees", "Haan, booked"])
    commit = next(a for a in actions if a.commits_booking)
    assert commit.slot_at is not None and commit.quote.amount_inr == 800


async def test_bug1_outside_limits_never_sets_slot_or_commits(brain):
    d = Delegation(granted=True, max_price_inr=1000, time_window_text="5 PM-7 PM",
                   user_words="you decide")
    brief = business_brief(task_type=TaskType.HEALTHCARE, delegation=d)
    actions, _ = await play(brain, brief, ["Sirf 7:30 pm ka slot hai, 1200 rupees", "theek hai"])
    assert not any(a.commits_booking or a.slot_at for a in actions)


async def test_bug17_repeated_blocks_switch_strategy(brain):
    brief = business_brief()
    actions, _ = await play(brain, brief, ["4 baje ya 6 baje, 400 rupees",
                                           "BLOCKED: odd", "BLOCKED: odd", "BLOCKED: odd"])
    rephrases = [a for a in actions if "dobara bolti" in (a.text or "")]
    assert len(rephrases) <= 1
    assert actions[-1].type == CallActionType.HANGUP


async def test_bug17_blocked_commitment_goes_to_callback(brain):
    d = Delegation(granted=True, max_price_inr=100, user_words="you decide")
    brief = business_brief(task_type=TaskType.HEALTHCARE, delegation=d)
    actions, _ = await play(brain, brief, [
        "5 pm, 800 rupees",
        "BLOCKED: commitment not allowed on this call (price outside the delegated ceiling)"])
    assert actions[-1].outcome == CallOutcome.PENDING_APPROVAL


def test_bug9_booking_reference_is_not_a_price():
    assert extract_amounts("Booking number LO196353 hai") == []
    assert extract_amounts("booking ref 196353") == []
    assert extract_amounts("Haircut ₹400, booking LO196353") == [400]
    assert extract_amounts("400 rupees lagenge") == [400]


def test_bug15_near_me_uses_last_pin_then_home():
    pin = Place(id="pin", owner_user_id="u1", label="Current location", ephemeral=True,
                location=GeoPoint(lat=12.97, lng=77.64))
    home = Place(id="home", owner_user_id="u1", label="Home", aliases=["ghar"])
    out = resolve(make_ctx(places=[home, pin]), "yahan ke paas AC repair karne wala dhundo")
    assert out.place_id == "pin" and out.location_text is None
    out = resolve(make_ctx(places=[home]), "yahan ke paas AC repair karne wala dhundo")
    assert out.place_id == "home" and out.location_text is None
    out = resolve(make_ctx(places=[home]), "Indiranagar ke paas AC repair")
    assert out.place_id is None and out.location_text == "indiranagar"
