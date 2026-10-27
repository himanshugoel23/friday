# ruff: noqa: E501
"""New guardrail wording: structure only (never the exact words); all PENDING founder approval."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from friday.chatbot.composer import LIMITS
from friday.guardrails import copy
from friday.guardrails.models import Category
from friday.guardrails.policy import POLICY

EMOJI = re.compile("[☀-➿\U0001f000-\U0001faff]")
ROOT = Path(__file__).resolve().parents[2]


def test_marked_pending_and_documented():
    assert copy.PENDING_FOUNDER_APPROVAL is True
    assert "PENDING_FOUNDER_APPROVAL" in (copy.__doc__ or "")
    pilot = (ROOT / "docs" / "CHATBOT_PILOT.md").read_text()
    for i in copy.all_ids():
        assert i in pilot, f"{i} is not listed in docs/CHATBOT_PILOT.md"


def test_every_line_has_three_languages_and_matching_variant_counts():
    for key, langs in copy.LINES.items():
        assert set(langs) == set(copy.LANGUAGES), key
        assert len({len(v) for v in langs.values()}) == 1, key
        assert 1 <= len(langs["en"]) <= 2


def test_refusal_categories_have_two_variants_so_wording_can_rotate():
    for cat, pol in POLICY.items():
        key = pol.reply_key
        if key in copy.LINES and pol.action.value in ("refuse", "redirect") and cat not in (
            Category.MINORS, Category.RATE_LIMITED, Category.OUT_OF_SCOPE
        ):
            assert copy.n_variants(key) == 2 or key in {"sensitive_unsolicited", "politics"}, key


@pytest.mark.parametrize("lang", copy.LANGUAGES)
def test_chat_quality_rules(lang):
    max_lines, max_chars = LIMITS["default"]
    for key, langs in copy.LINES.items():
        for text in langs[lang]:
            assert text.strip() == text and text, key
            assert not EMOJI.search(text), key
            assert len(text) <= max_chars + 40, (key, len(text))  # disclaimers/ack are short; refusals <= cap
            assert len(text.splitlines()) <= max_lines, key
            assert len(re.findall(r"[?？]", text)) <= 1, key


def test_safety_lines_carry_the_numbers():
    for lang in copy.LANGUAGES:
        text = copy.line("self_harm", lang)
        assert "14416" in text and "112" in text


def test_identity_line_is_truthful():
    assert "AI" in copy.line("identity", "en") and "AI" in copy.line("identity", "hinglish")


def test_existing_lines_are_looked_up_not_duplicated():
    from friday.chatbot import copy as chat_copy

    assert copy.line("safety_emergency", "en") == chat_copy.line("safety_emergency", "en")
    assert not set(copy.LINES) & set(chat_copy.LINES)
