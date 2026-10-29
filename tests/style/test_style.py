# ruff: noqa: E501
"""Style layer: checks, builders, owned-template enforcement, prompt block. Fakes only."""

from __future__ import annotations

import pytest

from friday.brain.prompts import system as brain_system
from friday.core.models import Language, Tone
from friday.style import StyleLayer, builders, check, prompt, wording


@pytest.fixture(autouse=True)
def _reset_prompt_switch():
    prompt.set_enabled(False)
    yield
    prompt.set_enabled(False)


def codes(text: str, **kw) -> list[str]:
    return [v.code for v in check.check(text, **kw)]


# ------------------------------------------------------------------ the checks
def test_clean_short_reply_has_no_violations():
    assert codes("On it. Checking the price now.") == []


def test_length_budget_lines_and_chars():
    six = "\n".join(f"line {i}" for i in range(6))
    assert "too_long" in codes(six)
    assert "too_long" not in codes(six, kind="result")
    assert "too_long" in codes("x" * 460)


def test_question_groups():
    assert check.question_groups("Home or PG?") == 1
    assert check.question_groups("Salary: 55L?\nNotice: immediate?\nCity: Delhi?") == 1  # grouped list = one group
    assert check.question_groups("Right?\nI will check prices.\nShould I book it?") == 2
    assert check.question_groups("Right? Should I book it?") == 2
    assert "many_questions" in codes("Right? Should I book it?")


def test_markdown_header_flagged():
    assert "markdown_header" in codes("## Result\nAtta 5 kg is Rs 250.")
    assert "markdown_header" not in codes("Result: atta 5 kg is Rs 250.")


def test_flat_refusal_and_confused_fallback():
    assert "flat_refusal" in codes("I can't do that.")
    assert "flat_refusal" not in codes("I can't set an alarm. I can set a reminder instead.")
    assert "flat_refusal" not in codes("Main alarm nahi laga sakti.", has_buttons=True)
    assert "flat_refusal" in codes("Main theek se samajh nahi payi. Call karun?")


def test_headline_first():
    assert check.headline_first("Atta 5 kg: Zepto is cheapest.\n1. Zepto Rs 250\n2. Blinkit Rs 262")
    assert not check.headline_first("1. Zepto Rs 250\n2. Blinkit Rs 262\nZepto is cheapest.")


def test_script_mirror_both_directions():
    assert check.script_violation("kal interview hai", "सब ठीक है, मैं देखती हूँ") is not None
    assert check.script_violation("kal interview hai", "Theek hai, reminder laga dun?") is None
    assert check.script_violation("मुझे कल इंटरव्यू है", "Interview kal hai, reminder laga dun?") is not None
    assert check.script_violation("मुझे कल इंटरव्यू है", "इंटरव्यू कल है, रिमाइंडर लगा दूँ?") is None


def test_cancel_and_proof_markers():
    assert check.has_cancel_wording("Cancelled. Nothing was charged or booked.")
    assert check.has_cancel_wording("Cancel kar diya. Kuch charge ya book nahi hua.")
    assert not check.has_cancel_wording("Cancelled.")
    assert check.has_proof_marks("Done. Proof:\nWhat: haircut")
    assert not check.has_proof_marks("Ho gaya.")


# ------------------------------------------------------------------ enforcement only changes shape
def test_split_keeps_words_and_budget():
    text = "Headline fact.\n\n" + "\n".join(f"{i}. option {i}" for i in range(1, 5)) + "\n\nExtra note one.\nExtra note two.\nExtra note three."
    parts = check.enforce(text, kind="text")
    assert len(parts) >= 2
    assert all(len(check.lines_of(p)) <= 5 for p in parts)
    assert "".join(p.replace("\n", "").replace(" ", "") for p in parts) == text.replace("\n", "").replace(" ", "")


def test_enforce_strips_header_markers_only():
    assert check.enforce("## Result\nAtta is Rs 250.") == ["Result\nAtta is Rs 250."]


def test_layer_off_is_passthrough_and_free_text_never_rewritten():
    off = StyleLayer(False)
    long = "\n".join(f"## line {i}" for i in range(12))
    assert off.fit(long) == [long] and off.flagged == []
    on = StyleLayer(True)
    free = "## Header\n" + "\n".join(f"line {i}" for i in range(12)) + "\nWhy? And why?"
    assert on.flag(free, source="model") == free  # flagged, never rewritten
    assert on.flagged and {v.code for v in on.flagged[0][1]} >= {"markdown_header", "too_long", "many_questions"}
    assert len(on.fit(long)) >= 2  # an owned template is split


# ------------------------------------------------------------------ builders
@pytest.mark.parametrize("lang", ["en", "hinglish"])
def test_builders_are_within_the_style_rules(lang):
    msgs = {
        "ack": (builders.ack("Zepto", lang), "text"),
        "slow": (builders.status("Zepto", lang), "text"),
        "step": (builders.status("Zepto", lang, step="comparing three sites"), "text"),
        "result": (builders.result("Atta 5 kg: Zepto is cheapest.", ["Zepto Rs 250 (Rs 50/kg)", "Blinkit Rs 262", "BigBasket Rs 270"], pick=("Zepto", "lowest per kg"), question="Want me to open the cart?", lang=lang), "result"),
        "grouped": (builders.grouped_questions([("Salary", "55L"), ("Notice", "immediate"), ("City", "Delhi")], lang), "text"),
        "assume": (builders.assumption("Gazebo Inn, Sector 39", lang), "text"),
        "confirm": (builders.confirm_irreversible(item="Veg pizza x1", place="Pizza Place", address="Sector 39", fees="Rs 30", total="Rs 480", next_step="I place the order and send tracking", lang=lang), "result"),
        "cancel": (builders.cancelled(lang), "text"),
        "cancel_order": (builders.cancelled(lang, ordered=True), "text"),
        "correction": (builders.correction("the fee is Rs 30, not Rs 40.", lang), "text"),
        "limit": (builders.honest_limit("set a phone alarm", "set a reminder or a wake-up call", lang), "text"),
    }
    for name, (text, kind) in msgs.items():
        assert check.check(text, kind=kind) == [], (name, text)
    assert check.has_cancel_wording(msgs["cancel"][0]) and check.has_cancel_wording(msgs["cancel_order"][0])
    assert check.headline_first(msgs["result"][0]) and msgs["result"][0].count("?") == 1
    total_word = "Total" if lang == "en" else "Kul"
    assert msgs["confirm"][0].index(total_word) < msgs["confirm"][0].index("?")


def test_result_caps_options_at_four():
    text = builders.result("Headline.", [f"o{i}" for i in range(9)], lang="en")
    assert text.count("\n") == 4  # headline + 4 options


def test_proof_card_shapes():
    base = dict(what="haircut price", where="Salon A", when="Thu 29 Oct, 10:00 AM", amount="Rs 400", reference="BK-4821", link="https://example.test/p")
    done = builders.proof_card(builders.ProofCard(outcome="done", has_screenshot=True, keep_days=90, **base), "en")
    assert done.startswith("Done. Proof:") and "Reference: BK-4821" in done and "Screenshot attached." in done
    assert "90 days" in done and "delete everything" in done
    stop = builders.proof_card(builders.ProofCard(outcome="checkout", what="cart", seen="payment page"), "en")
    assert "Nothing was charged" in stop and "Saw: payment page" in stop
    fail = builders.proof_card(builders.ProofCard(outcome="failed", what="form", seen="blocked by a check"), "hinglish")
    assert "Dikha: blocked by a check" in fail
    assert check.check(done, kind="proof") == []


def test_wording_is_pending_and_complete():
    assert wording.LINE_STATUS == "PENDING_FOUNDER_APPROVAL"
    assert all(set(row) == {"en", "hinglish"} for row in wording.TEXTS.values())


# ------------------------------------------------------------------ prompt block
def test_prompt_block_only_when_on():
    base = brain_system.system_prompt("summarize", tone=Tone.FRIENDLY, language=Language.HINGLISH)
    assert "CHAT STYLE" not in base
    prompt.set_enabled(True)
    on = brain_system.system_prompt("summarize", tone=Tone.FRIENDLY, language=Language.HINGLISH)
    assert "CHAT STYLE" in on and on.replace("\n" + prompt.STYLE_BLOCK, "") == base
    assert "CHAT STYLE" not in brain_system.system_prompt("call_turn")  # spoken prompts are untouched
    assert "CHAT STYLE" not in brain_system.system_prompt("extract")
