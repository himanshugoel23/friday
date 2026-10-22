"""The chat-quality rules, one test per rule (friday/chatbot/composer.py)."""

from __future__ import annotations

import pytest

from friday.chatbot import copy
from friday.chatbot.composer import (
    Composer,
    RuleViolation,
    buttons_for,
    detect_language,
    has_full_statement,
    has_statement,
    mirror_language,
)
from friday.core.models import ListMenu, ListRow, ReplyButton

C = Composer()
STRICT = Composer(strict=True)


def btn(*titles: str) -> list[ReplyButton]:
    return [ReplyButton(id=f"cb:{i}", title=t) for i, t in enumerate(titles)]


# ---------------------------------------------------------------- 1. length caps
def test_a_normal_message_may_have_three_lines_and_300_characters():
    ok = "Ek line.\nDoosri line.\nTeesri line."
    assert C.check(ok) == []
    assert any(p.startswith("lines") for p in C.check(ok + "\nChauthi line."))
    assert any(p.startswith("chars") for p in C.check("x" * 301))
    assert C.check("x" * 300) == []


def test_the_intro_may_be_longer_than_a_normal_message():
    intro = copy.line("intro", "hinglish")
    assert len(intro.split("\n")) > 3
    assert C.check(intro, kind="intro") == []
    assert any(p.startswith("lines") for p in C.check(intro))  # not allowed as a normal message


def test_an_empty_message_is_a_problem():
    assert any(p.startswith("empty") for p in C.check("  "))


# ---------------------------------------------------------------- 2. one question
def test_one_question_per_message():
    assert C.check("Aapka naam kya hai?") == []
    problems = C.check("Aapka naam kya hai? Aap kahan rehte hain?")
    assert any(p.startswith("one_question") for p in problems)


# ---------------------------------------------------------------- 3. buttons and lists
def test_at_most_three_buttons_with_titles_up_to_20_characters():
    assert C.check("Chuniye", btn("Haan", "Nahi", "Details")) == []
    assert any(p.startswith("buttons") for p in C.check("x", btn("a", "b", "c", "d")))
    assert C.check("x", btn("a" * 20)) == []
    # the model itself refuses a 21-character title; the composer also checks titles it is given
    long = ReplyButton.model_construct(id="cb:1", title="a" * 21)
    assert any("longer than 20" in p for p in C.check("x", [long]))


def test_button_titles_are_not_empty_or_duplicated():
    assert any("duplicate" in p for p in C.check("x", btn("Haan", "haan")))
    empty = ReplyButton.model_construct(id="cb:1", title=" ")
    assert any("empty" in p for p in C.check("x", [empty]))


def test_list_messages_are_limited_and_never_mixed_with_buttons():
    rows = [ListRow(id=f"cb:menu:{i}", title=f"Row {i}", description="d") for i in range(10)]
    menu = ListMenu(button="Menu", rows=rows)
    assert C.check("Chuniye", list_menu=menu) == []
    assert any("cannot also carry" in p for p in C.check("x", btn("a"), menu))
    many = ListMenu.model_construct(button="Menu", rows=rows + rows[:1], section=None)
    assert any("11 rows" in p for p in C.check("x", list_menu=many))
    wide = ListMenu.model_construct(
        button="a" * 21,
        rows=[ListRow.model_construct(id="x", title="t" * 25, description="d" * 73)],
        section=None,
    )
    problems = " ".join(C.check("x", list_menu=wide))
    assert "label longer" in problems and "row title longer" in problems
    assert "row description longer" in problems


# ---------------------------------------------------------------- 4. no repeated line
def test_a_line_is_not_repeated_in_a_message():
    assert any(p.startswith("repeat") for p in C.check("Theek hai.\nKuch aur.\nTheek hai."))
    out = C.compose("Theek hai.\nTheek hai.\nAage badhein?")
    assert out is not None and out.text == "Theek hai.\nAage badhein?"  # consecutive repeat dropped


def test_the_same_message_twice_in_a_row_is_replaced_by_the_shorter_alternative():
    first = C.compose("Aapka naam kya hai?", buttons=btn("Skip"))
    assert first is not None
    again = C.compose(
        "Aapka naam kya hai?",
        buttons=btn("Skip"),
        last_digest=first.digest,
        alt="Sirf naam likhiye.",
    )
    assert again is not None and again.text == "Sirf naam likhiye."
    # no alternative: nothing is sent at all
    assert C.compose("Aapka naam kya hai?", buttons=btn("Skip"), last_digest=first.digest) is None
    # alternative identical to the last one: nothing either
    alt_first = C.compose("Sirf naam likhiye.", buttons=btn("Skip"))
    assert alt_first is not None
    assert (
        C.compose(
            "Aapka naam kya hai?",
            buttons=btn("Skip"),
            last_digest=first.digest,
            alt="Sirf naam likhiye.",
        ).text  # type: ignore[union-attr]
        == "Sirf naam likhiye."
    )
    assert (
        C.compose(
            "Sirf naam likhiye.",
            buttons=btn("Skip"),
            last_digest=alt_first.digest,
            alt="Sirf naam likhiye.",
        )
        is None
    )


def test_a_different_message_is_sent_normally():
    first = C.compose("Ek.")
    assert first is not None
    nxt = C.compose("Do.", last_digest=first.digest)
    assert nxt is not None and nxt.text == "Do."


# ---------------------------------------------------------------- 5. language mirroring
@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("mujhe kal ka din batao", "hinglish"),
        ("mummy ko call karo", "hinglish"),
        ("Hello, can you help me with my bill please", "en"),
        ("I want to book a table for tomorrow", "en"),
        ("मुझे कल का दिन बताओ", "hi"),
        ("नमस्ते", "hi"),
        ("hi", None),
        ("hello", None),
        ("ok", None),
        ("9876543210", None),
        ("", None),
    ],
)
def test_detect_language(text, want):
    assert detect_language(text) == want


def test_mirror_language_falls_back_to_hinglish_or_the_current_language():
    assert mirror_language("hi") == "hinglish"
    assert mirror_language("hello", "en") == "en"
    assert mirror_language("please call my mother tomorrow", "hinglish") == "en"
    assert mirror_language("मेरा दिन", "hinglish") == "hi"


# ---------------------------------------------------------------- 6. the statement and the why
def test_the_statement_names_assistant_and_what_she_never_does():
    assert has_statement("Friday AI assistant hai; payment, OTP, PIN kabhi nahi maangti.") == []
    assert "assistant" in has_statement("Payment, OTP, PIN kabhi nahi.")
    assert any("never" in m for m in has_statement("Main AI assistant hoon."))
    assert has_full_statement(copy.line("intro", "hinglish")) == []
    missing = has_full_statement("AI assistant: payment, OTP, PIN kabhi nahi.")
    assert "own data" in missing and "delete anytime" in missing


def test_intro_and_closing_messages_must_carry_the_statement():
    assert any(p.startswith("statement") for p in C.check("Namaste, main Friday.", kind="intro"))
    assert any(p.startswith("statement") for p in C.check("Bas ho gaya.", kind="disclosure"))
    assert C.check(copy.line("done", "hinglish"), kind="disclosure") == []


def test_a_proactive_message_needs_its_reason():
    base = "Friday AI assistant hai; payment, OTP, PIN kabhi nahi maangti."
    assert any(p.startswith("why") for p in C.check(base, kind="proactive"))
    why = copy.line("why_generic", "hinglish")
    text = f"{base}\n{why}"
    assert C.check(text, kind="proactive", why=why) == []
    # compose appends the reason when the caller forgot it
    out = C.compose(base, kind="proactive", why=why)
    assert out is not None and why in out.text


# ---------------------------------------------------------------- strict and lenient
def test_strict_mode_raises_and_lenient_mode_repairs():
    with pytest.raises(RuleViolation) as e:
        STRICT.compose("a\nb\nc\nd")
    assert e.value.rule == "lines"
    out = C.compose("a\nb\nc\nd")
    assert out is not None and out.text == "a\nb\nc"
    long_btn = ReplyButton.model_construct(id="cb:1", title="x" * 30)
    fixed = C.compose("hello", buttons=[long_btn] + btn("a", "b", "c"))
    assert fixed is not None and len(fixed.buttons) == 3
    assert all(len(b.title) <= 20 for b in fixed.buttons)


def test_the_footer_is_added_once_to_a_step_when_asked():
    footer = copy.line("footer_short", "hinglish")
    out = C.compose("Aapka naam kya hai?", footer=footer)
    assert out is not None and out.text.endswith(footer)
    again = C.compose(out.text, footer=footer)
    assert again is not None and again.text.count(footer) == 1


def test_buttons_for_builds_reply_buttons():
    b = buttons_for(("cb:skip", "Skip"))
    assert b[0].id == "cb:skip" and b[0].title == "Skip"
