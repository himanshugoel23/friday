"""The pending-approval copy module: structure only, never the exact words."""

from __future__ import annotations

import re
import string

import pytest

from friday.chatbot import copy
from friday.chatbot.composer import Composer, has_full_statement, has_statement

SAMPLE = {
    "name": "Rahul", "language": "Hinglish", "current": "Hinglish", "city": "Pune",
    "who": "Mummy", "masked": "+91 98765 432XX", "label": "Home", "phone": "+91******3210",
    "text": "kuch bhi likha hua sawaal", "expr": "2 + 2", "result": "4", "time": "2:11 PM",
    "date": "Friday, 23 October 2026",
}  # fmt: skip
EMOJI = re.compile("[☀-➿\U0001f000-\U0001faff\U00002600-\U000027bf]")
C = Composer()


def fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_the_module_is_marked_pending_founder_approval():
    assert copy.PENDING_FOUNDER_APPROVAL is True
    assert "PENDING_FOUNDER_APPROVAL" in (copy.__doc__ or "")
    assert len(copy.WORDING_VERSION) <= 20  # Consent.policy_version is 20 characters


@pytest.mark.parametrize("table", [copy.LINES, copy.BUTTONS])
def test_every_entry_has_hinglish_hindi_and_english(table):
    for key, variants in table.items():
        assert set(variants) == set(copy.LANGUAGES), key


def test_every_row_has_the_three_languages():
    for key, variants in copy.ROWS.items():
        assert set(variants) == set(copy.LANGUAGES), key


def test_placeholders_are_the_same_in_all_three_languages():
    for key, variants in copy.LINES.items():
        sets = {lang: fields(text) for lang, text in variants.items()}
        assert len({frozenset(s) for s in sets.values()}) == 1, (key, sets)
        assert sets["hinglish"] <= set(SAMPLE), (key, sets)


def test_every_line_passes_the_composer_rules_in_every_language():
    for key, variants in copy.LINES.items():
        kind = copy.kind_of(key)
        for lang in copy.LANGUAGES:
            if key.startswith(("mark_", "footer")):
                continue  # fragments that are appended to other text
            text = copy.line(key, lang, **{f: SAMPLE[f] for f in fields(variants[lang])})
            if kind == "internal":
                assert C.check(text, kind=kind) == [], (key, lang)
                continue
            assert C.check(text, kind=kind) == [], (key, lang, C.check(text, kind=kind))


def test_the_intro_and_the_waitlist_say_who_she_is_and_what_she_never_does_in_all_languages():
    for key in ("intro", "details", "waitlist"):
        for lang in copy.LANGUAGES:
            text = copy.line(key, lang)
            assert has_statement(text) == [], (key, lang)
    for lang in copy.LANGUAGES:
        assert has_full_statement(copy.line("intro", lang)) == [], lang
        assert has_statement(copy.line("done", lang)) == [], lang
        assert has_statement(copy.line("footer_short", lang)) == [], lang


def test_the_why_clause_names_a_reason_and_how_to_stop():
    for lang in copy.LANGUAGES:
        text = copy.line("why_generic", lang)
        assert "stop" in text.lower()


def test_button_titles_fit_whatsapp():
    for key, variants in copy.BUTTONS.items():
        for lang, title in variants.items():
            assert 1 <= len(title) <= 20, (key, lang)


def test_list_rows_fit_whatsapp_even_with_the_pilot_marker():
    for key, variants in copy.ROWS.items():
        for lang, (title, desc) in variants.items():
            assert 1 <= len(title) <= 24, (key, lang)
            marker = max(len(copy.line(m, lang)) for m in ("mark_pilot", "mark_soon"))
            assert len(desc) + 1 + marker <= 72, (key, lang)
    assert set(copy.PILOT_ROWS) <= set(copy.ROWS)
    assert len(copy.ROWS) <= 10


def test_no_emojis():
    for variants in [*copy.LINES.values(), *copy.BUTTONS.values()]:
        for text in variants.values():
            assert not EMOJI.search(text)
    for variants in copy.ROWS.values():
        for pair in variants.values():
            assert not any(EMOJI.search(t) for t in pair)


def test_hindi_is_devanagari_and_hinglish_is_roman():
    deva = re.compile("[ऀ-ॿ]")
    for key, variants in copy.LINES.items():
        assert deva.search(variants["hi"]), key
        assert not deva.search(variants["hinglish"]), key
        assert not deva.search(variants["en"]), key


def test_ids_cover_every_line_button_and_row_exactly_once():
    ids = copy.all_ids()
    assert len(ids) == len(set(ids)) == len(copy.LINES) + len(copy.BUTTONS) + len(copy.ROWS)
    assert "chatbot.line.intro" in ids and "chatbot.button.consent_yes" in ids
    assert "chatbot.row.call" in ids


def test_unknown_language_falls_back_to_hinglish():
    assert copy.line("refused", "ta") == copy.line("refused", "hinglish")
    assert copy.button("skip", "ta") == copy.button("skip", "hinglish")


def test_the_closing_message_and_the_menu_marker_exist():
    assert copy.kind_of("done") == "disclosure"
    assert copy.kind_of("intro") == "intro"
    assert copy.kind_of("ask_name") == "default"
