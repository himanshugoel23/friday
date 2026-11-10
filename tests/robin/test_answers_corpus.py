# ruff: noqa: E501
"""T11 acceptance corpus: short Hindi / Hinglish / English answers as an STT would hand them over, with the class Robin must read.
(text, confidence, expected) where expected is one of silence | help | stop | no | fine | yes | unclear. Invented phrases, no personal data."""

from __future__ import annotations

import pytest

from friday.robin import answers as ans

CORPUS = [
    # yes
    ("haan", 0.9, "yes"), ("haan ji", 0.8, "yes"), ("haanji", 0.7, "yes"), ("ji haan", 0.8, "yes"), ("hnji", 0.6, "yes"), ("हाँ", 0.9, "yes"), ("हां जी", 0.8, "yes"),
    ("yes", 0.9, "yes"), ("bilkul", 0.8, "yes"), ("haan maine kha liya", 0.7, "yes"), ("han", 0.5, "yes"), ("hmm", 0.5, "yes"), ("ji", 0.6, "yes"),
    ("ठीक", 0.8, "yes"), ("haan theek", 0.8, "yes"),
    # no
    ("nahi", 0.9, "no"), ("nahin", 0.8, "no"), ("nahi nahi", 0.8, "no"), ("नहीं", 0.9, "no"), ("nhi", 0.6, "no"), ("no", 0.9, "no"), ("ji nahi", 0.8, "no"),
    ("haan nahi", 0.7, "no"), ("nahi aaj nahi", 0.8, "no"), ("theek nahi hoon", 0.8, "no"), ("नहीं नहीं", 0.8, "no"), ("nhin", 0.5, "no"),
    # fine
    ("theek hoon", 0.9, "fine"), ("main theek hoon", 0.9, "fine"), ("sab theek hai", 0.8, "fine"), ("ठीक हूँ", 0.8, "fine"), ("i am fine", 0.9, "fine"), ("theek hun", 0.7, "fine"),
    # help / threat (always win, even at low confidence)
    ("madad", 0.9, "help"), ("madad karo", 0.9, "help"), ("मदद", 0.9, "help"), ("bachao", 0.4, "help"), ("help", 0.1, "help"), ("ambulance bulao", 0.5, "help"),
    ("mujhe khatra hai", 0.6, "help"), ("koi dhamki de raha hai", 0.7, "help"), ("haan madad chahiye", 0.8, "help"), ("theek nahi hoon madad karo", 0.8, "help"),
    # stop
    ("ruk jao", 0.9, "stop"), ("band karo", 0.8, "stop"), ("phone mat karo", 0.7, "stop"), ("stop", 0.9, "stop"), ("रुको", 0.8, "stop"),
    # silence
    ("", None, "silence"), ("   ", 0.9, "silence"),
    # unclear: noise, off-topic, low confidence yes/no
    ("haan", 0.1, "unclear"), ("nahi", 0.2, "unclear"), ("achha", 0.9, "unclear"), ("pata nahi kya", None, "no"), ("kya", 0.9, "unclear"), ("kaun", 0.8, "unclear"), ("hello hello", 0.8, "unclear"),
]


@pytest.mark.parametrize(("text", "conf", "want"), CORPUS)
def test_corpus(text, conf, want):
    assert ans.classify(text, conf) == want, (text, conf)


def test_corpus_accuracy_floor_and_safety_words_never_missed():
    got = [ans.classify(t, c) for t, c, _ in CORPUS]
    assert sum(g == w for g, (_, _, w) in zip(got, CORPUS, strict=True)) == len(CORPUS)
    for (t, _c, w), g in zip(CORPUS, got, strict=True):
        if w in ("help", "stop"):
            assert g == w, f"safety word missed: {t!r}"
        else:
            assert g not in ("help", "stop"), f"false safety hit: {t!r}"


def test_low_confidence_is_never_read_as_yes_or_fine():
    for t in ("haan", "theek hoon", "bilkul"):
        assert ans.classify(t, 0.05) == "unclear"


# ---------------------------------------------------------------- fall / chest pain / breathing are SOS-grade help; "help" is a whole word; stretched spellings still count
FALL_CHEST_HELP = [
    "main gir gayi hoon, uth nahi pa rahi", "मैं गिर गया हूँ, उठ नहीं पा रहा", "main gir gaya hoon", "gir gayi hu", "bathroom mein gir padi hoon", "uth nahi sakta", "utha nahi ja raha",
    "seene mein bahut dard ho raha hai", "mere seene mein dard hai", "सीने में बहुत दर्द है", "chhati mein dard", "chakkar aa raha hai, gir jaunga", "चक्कर आ रहा है गिर जाऊँगी",
    "I fell down and can't get up from the floor", "I have chest pain", "pain in my chest", "I can't breathe", "saans nahi aa rahi", "saans lene mein takleef", "लगता है heart attack है",
    "behosh ho jaunga", "I've fallen",
]
STRETCHED_HELP = ["helppp", "HELPPPP", "madadd", "madaaad", "bachaooo", "bachaaao", "मददद", "helpme", "help!!!", "plzzz helllp", "bachalo", "hellp me"]
NOT_HELP = [
    "the bank clerk was very helpful today", "padosi bahut madadgar hain", "helpline number do", "he is helping me", "paani gir gaya", "chai gir gayi", "sone ka bhav gir gaya hai",
    "sar mein dard hai", "dard ki dawa de do", "seene mein dard nahi hai", "I have no chest pain", "I fell asleep early", "पानी गिर गया", "mera chakkar lagane ka mann hai", "unhelpful staff",
]


@pytest.mark.parametrize("text", FALL_CHEST_HELP + STRETCHED_HELP)
def test_fall_chest_and_stretched_help_are_help(text):
    assert ans.is_help(text), text
    assert ans.classify(text, 0.05) == "help", text  # even at very low STT confidence


@pytest.mark.parametrize("text", NOT_HELP)
def test_whole_word_and_phrase_matching_does_not_fire_on_everyday_talk(text):
    assert not ans.is_help(text), text


def test_help_recall_never_dropped_against_the_old_substring_rule():
    """Every phrase the old substring rule matched as a help WORD (standing alone, with typical suffixes/stretches) still matches now."""
    for w in ("help", "madad", "bachao", "bachaao", "ambulance", "emergency", "मदद", "बचाओ", "एम्बुलेंस"):
        for form in (w, w.upper(), f"{w}!", f"{w}, {w}", f"mujhe {w} chahiye", f"{w[:-1]}{w[-1] * 3}" if w.isascii() else w):
            assert ans.is_help(form), form
