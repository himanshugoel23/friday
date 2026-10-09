"""Copy, deterministic understanding and the guard (pure, no app)."""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from friday.brain import frontdoor as fd
from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.models import (
    CallBrief,
    CallMode,
    ContactTarget,
    Language,
    TargetKind,
    TaskType,
)
from friday.core.safety import check_speech
from friday.voice.frontdoor import FrontDoorGuard, estimate_call_cost_inr

BRIEF = CallBrief(
    task_id="t", requester_user_id="u", task_type=TaskType.ENQUIRY, goal="x",
    target=ContactTarget(kind=TargetKind.PERSON, name="c", phone="+919812345678"),
    on_behalf_of="Friday", mode=CallMode.FRONT_DOOR,
)
FILLER = re.compile(r"\b(um+|uh+|hmm+|er+m)\b", re.I)
EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿]")


def test_every_fixed_line_exists_in_all_three_languages_and_is_clean():
    for key, table in fd.LINES.items():
        assert set(table) == {Language.EN, Language.HINGLISH, Language.HI}, key
        for lang, text in table.items():
            probe = text.format(name="Asha", goal="book a haircut")
            assert not FILLER.search(probe) and not EMOJI.search(probe), (key, lang)
            assert check_speech(probe, BRIEF).allowed, (key, lang)  # no PIN/OTP/long numbers
            assert len(probe) < 420, (key, lang)  # short, one breath at a time


def test_the_ai_disclosure_comes_first_in_every_greeting_and_rejection():
    for key in ("disclosure", "greeting_new", "reject_private", "reject_busy", "reject_limit",
                "reject_unavailable"):
        for lang, text in fd.LINES[key].items():
            assert "AI" in text.split("।")[0].split(".")[0], (key, lang)
    assert fd.LINES["greeting_new"][Language.EN].startswith("Hello, this is Friday, an AI")


def test_no_line_ever_asks_for_a_pin_or_otp_to_be_spoken():
    asking = re.compile(r"(say|tell|bolo|bataiye|boliye|बोलिए|बताइए)[^.]{0,30}(pin|otp)", re.I)
    for key, table in fd.LINES.items():
        if key == "secret_refusal":  # the one line that tells callers NOT to say them
            continue
        for text in table.values():
            assert not asking.search(text), key


def test_feminine_hindi_forms_are_used():
    for key in ("capabilities", "bot_answer", "task_started_callback"):
        text = fd.LINES[key][Language.HINGLISH]
        assert not re.search(r"\b(karta|sakta|karunga|raha)\b", text), key


def test_prerender_plan_covers_the_fixed_lines_not_the_callers_words():
    plan = fd.prerender_plan(Language.HINGLISH)
    assert set(plan) == {Language.HINGLISH, Language.EN, Language.HI}
    assert fd.line("disclosure", Language.HINGLISH) in plan[Language.HINGLISH]
    assert fd.line("greeting_new", Language.HI) in plan[Language.HI]
    for texts in plan.values():
        assert not any("{" in t for t in texts)
    assert len(plan[Language.HINGLISH]) > len(plan[Language.EN])


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Asha", "Asha"), ("mera naam Rahul hai", "Rahul"), ("my name is priya nair", "Priya Nair"),
        ("haan main Suresh bol raha hoon", "Suresh"), ("I'm Dev", "Dev"), ("मेरा नाम आशा है", "आशा"),
        ("what is this", None), ("book a haircut please", None), ("12345", None),
        ("my pin is 4826", None), ("", None), ("a b c d e f", None),
    ],
)
def test_name_extraction(text, name):
    assert fd.extract_name(text) == name


@pytest.mark.parametrize(
    ("text", "answer"),
    [("haan", True), ("yes please", True), ("ji haan", True), ("nahi", False), ("no", False),
     ("नहीं", False), ("हाँ", True), ("haan nahi", None), ("pata nahi kya hoga", False),
     ("what", None)],
)
def test_yes_no(text, answer):
    assert fd.yes_no(text) is answer


def test_consent_needs_an_explicit_yes():
    assert fd.consents_yes("haan") and fd.consents_yes("yes I agree") and fd.consents_yes("हाँ")
    assert not fd.consents_yes("ji") and not fd.consents_yes("hmm") and not fd.consents_yes("no")
    assert not fd.consents_yes("haan nahi")


def test_rights_and_honesty_questions_are_recognised_without_an_llm():
    for t in ("delete everything", "sab delete kar do", "delete my data", "सब डिलीट कर दो"):
        assert fd.wants_delete(t), t
    for t in ("are you a bot?", "kya aap insaan ho", "is this a robot", "are you human", "bot ho kya"):
        assert fd.asks_if_bot(t), t
    for t in ("who are you", "what can you do", "aap kaun ho", "tum kya kar sakti ho"):
        assert fd.asks_who(t), t
    assert fd.wants_to_end("ok bye") and fd.wants_to_end("that's all") and not fd.wants_to_end("book")


def test_secrets_are_recognised():
    for t in ("mera pin 4826 hai", "the OTP is 123456", "cvv 123", "password hai abc", "ओटीपी"):
        assert fd.mentions_secret(t), t
    assert not fd.mentions_secret("book a haircut at 6 pm")


def test_language_choice_words():
    assert fd.parse_language_choice("Hindi") == Language.HI
    assert fd.parse_language_choice("English please") == Language.EN
    assert fd.parse_language_choice("dono chalega") == Language.HINGLISH
    assert fd.parse_language_choice("Tamil") == Language.TA
    assert fd.parse_language_choice("whatever") is None


def test_regional_languages_are_answered_in_english_copy():
    assert fd.pick_language(Language.TA) == Language.EN
    assert fd.line("goodbye", Language.TA) == fd.LINES["goodbye"][Language.EN]


def test_speakable_strips_markdown_emoji_links_and_cuts_long_text():
    assert fd.speakable("**Booked!** 😀 see https://x.y/z") == "Booked! see"
    long = "One sentence here. " * 30
    assert len(fd.speakable(long)) <= 220 and fd.speakable(long).endswith(".")
    assert fd.spoken_goal("Book a haircut for Rahul tomorrow 6-8pm.") == (
        "book a haircut for Rahul tomorrow 6-8pm"
    )


def settings(**kw) -> Settings:
    return Settings(_env_file=None, mode="simulator", env="test", **kw)


def test_guard_per_caller_limits_and_windows():
    clock = FakeClock(datetime(2026, 1, 5, 10, 0, tzinfo=IST))
    g = FrontDoorGuard(settings(frontdoor_per_caller_per_hour=2, frontdoor_per_caller_per_day=3),
                       clock)
    for i in range(2):
        assert g.check("a") is None
        g.admit(f"c{i}", "a")
        g.release(f"c{i}", 0.5)
    assert g.check("a") == "reject_limit" and g.check("b") is None  # per caller, not global
    clock.advance(3601)
    assert g.check("a") is None  # the hourly window slides
    g.admit("c3", "a")
    g.release("c3", 0.5)
    assert g.check("a") == "reject_limit"  # but the daily cap (3) holds
    clock.advance(86400)
    assert g.check("a") is None


def test_guard_one_live_call_in_the_pilot_and_n_outside():
    clock = FakeClock()
    g = FrontDoorGuard(settings(profile="pilot", frontdoor_max_concurrent=5), clock)
    assert g.max_concurrent == 1
    g.admit("c1", "a")
    assert g.check("b") == "reject_busy"
    g.release("c1", 0)
    assert g.check("b") is None
    g2 = FrontDoorGuard(settings(frontdoor_max_concurrent=3), clock)
    for i in range(3):
        g2.admit(f"c{i}", f"k{i}")
    assert g2.check("z") == "reject_busy"


def test_guard_global_limit_and_spend_cap():
    clock = FakeClock()
    g = FrontDoorGuard(settings(profile="pilot", frontdoor_global_per_hour=2), clock)
    assert g.spend_cap_inr == 25.0  # the pilot cap by default
    for i in range(2):
        g.admit(f"c{i}", f"k{i}")
        g.release(f"c{i}", 1.0)
    assert g.check("new") == "reject_busy"
    g = FrontDoorGuard(settings(profile="pilot"), clock)
    g.admit("c", "k")
    g.release("c", 25.0)
    assert g.check("new") == "reject_unavailable"
    assert FrontDoorGuard(settings(), clock).spend_cap_inr is None  # no cap outside the pilot


def test_guard_blocks_repeat_rejects():
    g = FrontDoorGuard(settings(), FakeClock())
    assert [g.note_reject("x") for _ in range(5)] == [False, False, False, True, True]
    assert g.rejected_too_often("x") and not g.rejected_too_often("y")


def test_call_limits_by_profile():
    assert FrontDoorGuard(settings(profile="pilot"), FakeClock()).max_call_s() == 180
    assert FrontDoorGuard(settings(), FakeClock()).max_call_s() == 300


def test_cost_estimate_is_small_and_grows_with_time_and_tts():
    short = estimate_call_cost_inr(30, 0, 0)
    assert 0.5 < short < 1.0
    assert estimate_call_cost_inr(30, 1000, 2) > short
    assert estimate_call_cost_inr(0, 0, 0) == 0.0


def test_pilot_dial_rule():
    off = settings()  # simulator + default profile: simulated businesses are fine
    assert not off.pilot_dial_blocked("+918040000001")
    on = settings(profile="pilot", pilot_block_business_calls=True,
                  pilot_allowed_numbers=["+919812345678"])
    assert on.pilot_dial_blocked("+918040000001") and on.pilot_dial_blocked(None)
    assert not on.pilot_dial_blocked("+919812345678")
    auto = Settings(_env_file=None, mode="live", profile="pilot", llm_provider="fake")
    assert auto.pilot_blocks_business_calls  # automatic in a live pilot
    assert not settings(profile="pilot").pilot_blocks_business_calls  # not in the simulator
