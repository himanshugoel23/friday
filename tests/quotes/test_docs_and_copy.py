# ruff: noqa: E501
"""The document lists every message; copy rules hold for the whole table."""

from __future__ import annotations

import re
from pathlib import Path

from friday.quotes.messages import LANGS, MESSAGES, SERVICE_LABELS, msg, services_text

DOC = Path(__file__).resolve().parents[2] / "docs" / "WHATSAPP_QUOTES_FLOW.md"


def test_doc_lists_every_message_in_every_language():
    doc = DOC.read_text(encoding="utf-8")
    for key, table in MESSAGES.items():
        assert f"**{key}**" in doc, key
        for lang in LANGS:
            assert table[lang] in doc, (key, lang)


def test_every_message_has_all_three_languages_and_no_emoji():
    for key, table in MESSAGES.items():
        assert set(table) == set(LANGS), key
        for text in table.values():
            assert not any(ord(ch) >= 0x1F000 for ch in text), key
            assert len(text) <= 400, key


def test_button_titles_fit_whatsapp():
    for key in ("btn_call", "btn_change", "btn_retry", "btn_others"):
        for lang in LANGS:
            assert len(MESSAGES[key][lang]) <= 20


def test_placeholders_match_across_languages():
    for key, table in MESSAGES.items():
        names = {frozenset(re.findall(r"\{(\w+)\}", t)) for t in table.values()}
        assert len(names) == 1, key


def test_services_text_joins_in_the_users_language():
    assert services_text(["haircut", "beard trim"], "hinglish") == "haircut aur beard trim"
    assert services_text(["haircut", "beard trim"], "en") == "haircut and beard trim"
    assert services_text(["haircut"], "hi") == "हेयरकट"
    assert msg("cancelled", "en").startswith("Okay, cancelled")
    assert set(SERVICE_LABELS) >= {"haircut", "beard trim", "facial"}
