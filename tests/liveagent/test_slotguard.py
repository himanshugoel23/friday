# ruff: noqa: E501
"""Guards: grounded slots, numbers, private leaks, secrets, must_not_say, repeats, commitments."""

from __future__ import annotations

import pytest

from friday.liveagent.contracts import CalleeKind, CallLanguage, Limits
from friday.liveagent.ports import HeardUtterance
from friday.liveagent.report import mask_numbers
from friday.liveagent.simulation.briefs import make_brief
from friday.liveagent.slotguard import (
    GuardContext,
    check_line,
    claims_to_be_user,
    denies_being_ai,
    judge_commitment,
    must_not_say_hits,
    private_leaks,
    public_brief_view,
    verify_slots,
)
from friday.liveagent.understand_callee import understand

BRIEF = make_brief(CalleeKind.FAMILY_ELDER, CallLanguage.HINGLISH, must_not_say=["surprise party"])


def ctx(**kw) -> GuardContext:
    return GuardContext(brief=BRIEF, **kw)


def test_clean_brief_line_passes() -> None:
    assert check_line("Kal shaam 5 baje doctor ke paas jana hai.", ctx()).ok


def test_ungrounded_time_and_amount_are_blocked() -> None:
    r = check_line("Main kal shaam 7 baje aa jaungi", ctx())
    assert r.has("ungrounded_number")
    r = check_line("Aap 4500 rupay de dijiye", ctx())
    assert r.has("ungrounded_number")


def test_number_from_the_callee_may_be_read_back() -> None:
    assert check_line("Theek hai, 3 baje", ctx(heard_text="haan teen baje aa jaunga")).ok
    assert check_line("Theek hai, 400 rupay", ctx(heard_text="400 rupay lagenge")).ok


def test_money_ceiling_is_not_grounded() -> None:
    b = make_brief(CalleeKind.PROVIDER, CallLanguage.HINGLISH)  # max_amount_inr=500
    assert check_line("Hum 500 rupay tak de sakte hain", GuardContext(brief=b)).has(
        "ungrounded_number"
    )


@pytest.mark.parametrize(
    "line",
    [
        "Unki salary Rs 85000 per month hai",
        "Wo Metformin leti hain",
        "Unke account mein 240000 rupees hain",
        "Wo Flat 402 Green Park mein rehte hain",
    ],
)
def test_private_facts_never_leak(line: str) -> None:
    assert private_leaks(line, BRIEF)
    assert check_line(line, ctx()).has("private_leak")


def test_private_fact_that_is_also_shareable_is_not_a_leak() -> None:
    b = make_brief(
        CalleeKind.FAMILY_ELDER,
        CallLanguage.HINGLISH,
        private_facts={"x": "Rohan shaam tak aa jayenge"},
    )
    assert not private_leaks("Rohan shaam tak aa jayenge", b)


def test_secret_wording_with_digits_is_blocked() -> None:
    assert check_line("Mera OTP 482913 hai", ctx()).has("secret_or_number")
    assert check_line("Card number 4111 1111 1111 1111", ctx()).has("secret_or_number")


def test_must_not_say() -> None:
    assert must_not_say_hits("Wo ek Surprise Party kar rahe hain", BRIEF)
    assert check_line("Wo ek surprise party kar rahe hain", ctx()).has("must_not_say")


def test_repeat_guard() -> None:
    assert check_line(
        "Hello, aap line par hain?", ctx(friday_lines=["Hello, aap line par hain?"])
    ).has("repeat")
    assert check_line(
        "Hello, aap line par hain?",
        ctx(friday_lines=["Hello, aap line par hain?"], allow_repeat=True),
    ).ok


def test_never_claims_to_be_the_user_or_to_be_human() -> None:
    assert claims_to_be_user("Main Rohan bol raha hoon", BRIEF)
    assert claims_to_be_user("This is Rohan", BRIEF)
    assert not claims_to_be_user("This is Friday, Rohan's assistant", BRIEF)
    assert denies_being_ai("Main robot nahi hoon")
    assert denies_being_ai("I am not a robot")
    assert denies_being_ai("main insaan hoon")
    assert check_line("I am a human being", ctx()).has("denies_ai")


def test_generated_text_that_promises_is_flagged() -> None:
    assert check_line("Haan main confirm karti hoon, kal shaam 5 baje pakka", ctx()).has(
        "commitment"
    )


def test_verify_slots_sources() -> None:
    b = BRIEF
    assert not verify_slots(
        {"user": "Rohan", "question": b.ask_list[0], "message": b.must_say[0]}, b, ""
    )
    assert verify_slots({"user": "Somebody"}, b, "")
    assert verify_slots({"question": "Aapki salary kitni hai?"}, b, "")
    assert verify_slots({"fact": "Rs 85000 per month"}, b, "")  # a private value is not a fact
    assert not verify_slots({"fact": b.shareable_facts["timing"]}, b, "")
    assert verify_slots({"nonsense": "x"}, b, "")


def test_verify_value_slot_comes_from_callee_words() -> None:
    assert not verify_slots({"value": "kal shaam 6 baje"}, BRIEF, "haan kal shaam 6 baje karna")
    assert verify_slots({"value": "kal shaam 9 baje"}, BRIEF, "haan kal shaam 6 baje karna")


def test_public_view_has_no_private_data() -> None:
    view = str(public_brief_view(BRIEF))
    for v in BRIEF.private_facts.values():
        assert v not in view
    assert "max_amount" not in view


LIMITS = Limits(
    max_amount_inr=500, allowed_commitments=["visit", "time"], allowed_times=["kal subah 10 baje"]
)


def j(text: str, limits: Limits = LIMITS):
    return judge_commitment(understand(HeardUtterance(text=text)), limits)


def test_commitment_inside_limits() -> None:
    v = j("kal subah 10 baje aa jaoon? pakka karo")
    assert v.allowed, v.reason


@pytest.mark.parametrize(
    "text",
    [
        "kal subah 7 baje aa jaunga, pakka bolo",
        "pakka bolo na",
        "book kar do pakka",
        "kal subah 10 baje aa jao, 900 rupay pakka",
    ],
)
def test_commitment_outside_limits_needs_user(text: str) -> None:
    assert not j(text).allowed


def test_no_commitment_when_brief_allows_none() -> None:
    assert not j("kal subah 10 baje aa jao pakka", Limits()).allowed


def test_masking() -> None:
    assert "9876501234" not in mask_numbers("mera number 9876501234 hai")
    assert mask_numbers("9876501234").endswith("34")
    assert "98765 01234" not in mask_numbers("98765 01234")
    assert "[number]" in mask_numbers("nau aath saat chhe paanch char teen do ek")
    assert mask_numbers("kal 5 baje") == "kal 5 baje"
