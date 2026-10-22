"""The Devanagari normaliser: digits, number words, loan words, mixed script, script detection."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from friday.lang_dev import detect_script, normalise_text, parse_number_phrase
from friday.lang_dev.normalise import mirror_script
from friday.lang_dev.reply import register_variant, to_script, variant_for
from friday.lang_dev.translit import transliterate_word


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("कल 2 बजे इंटरव्यू है", "kal 2 baje interview hai"),
        ("कल 2 बजे interview है", "kal 2 baje interview hai"),
        ("कल शाम सवा पाँच बजे फ्लाइट है", "kal shaam sawa 5 baje flight hai"),
        ("परसों सुबह साढ़े नौ बजे मीटिंग", "parso subah saade 9 baje meeting"),
        ("कल डेढ़ बजे लंच", "kal dedh baje lunch"),
        ("कल ढाई बजे मीटिंग", "kal dhai baje meeting"),
        ("कल पौने छह बजे ट्रेन", "kal paune 6 baje train"),
        ("पाँच सौ रुपये का बिल", "500 rupaye ka bill"),
        ("डेढ़ सौ का रिचार्ज", "150 ka recharge"),
        ("मम्मी को फोन करके बताओ", "mummy ko phone karke batao"),
        ("मत पूछो", "mat poocho"),
        ("बिजली का बिल २० तारीख को", "bijli ka bill 20 tarikh ko"),
        ("२५ अक्टूबर", "25 october"),
        ("कार्ड बिल फोन डॉक्टर रेस्टोरेंट", "card bill phone doctor restaurant"),
        ("मेरे पास एचडीएफसी रीगालिया है", "mere paas hdfc regalia hai"),
        ("तुम्हें क्या याद है।", "tumhe kya yaad hai."),
    ],
)
def test_normalised_to_the_spellings_the_rule_banks_use(typed: str, expected: str) -> None:
    assert normalise_text(typed).text == expected


def test_roman_text_is_returned_untouched() -> None:
    for text in ["kal 2 baje interview hai", "Zomato pe 640", "hello  there", "", "₹500 ka bill"]:
        n = normalise_text(text)
        assert n.text == text and not n.changed and n.script == "roman"


def test_the_original_is_kept() -> None:
    n = normalise_text("कल 2 बजे interview है")
    assert n.original == "कल 2 बजे interview है"
    assert n.changed and n.script == "mixed"


def test_devanagari_digits_alone() -> None:
    assert normalise_text("१२३४").text == "1234"
    assert normalise_text("₹५००").text == "₹500"
    assert normalise_text("०९:३०").text == "09:30"


def test_bas_and_bus_are_told_apart_by_their_neighbours() -> None:
    assert normalise_text("बस करो").text == "bas karo"
    assert normalise_text("रात 11 बजे बस है").text == "raat 11 baje bus hai"
    assert normalise_text("बस स्टैंड").text.startswith("bus ")


def test_a_verb_do_is_not_the_number_two() -> None:
    assert normalise_text("बता दो").text == "bata do"
    assert normalise_text("हटा दो").text == "hata do"
    assert normalise_text("दो बजे").text == "2 baje"
    assert normalise_text("एक कार्ड").text == "ek card"


@pytest.mark.parametrize(
    ("phrase", "value"),
    [
        ("पाँच सौ", 500),
        ("पांच सौ", 500),
        ("डेढ़ सौ", 150),
        ("ढाई सौ", 250),
        ("सवा सौ", 125),
        ("सवा पाँच", Decimal("5.25")),
        ("साढ़े तीन", Decimal("3.5")),
        ("पौने तीन सौ", 275),
        ("साढ़े तीन हज़ार", 3500),
        ("ढाई लाख", 250000),
        ("एक लाख बीस हज़ार", 120000),
        ("दो हज़ार पाँच सौ बीस", 2520),
        ("पच्चीस", 25),
        ("निन्यानवे", 99),
        ("५००", 500),
    ],
)
def test_hindi_number_words_to_values(phrase: str, value: int | Decimal) -> None:
    assert parse_number_phrase(phrase) == Decimal(value)


def test_two_plain_numbers_in_a_row_are_not_one_number() -> None:
    assert parse_number_phrase("पाँच दस") is None
    assert parse_number_phrase("कल") is None


def test_script_detection_and_mirroring() -> None:
    assert detect_script("kal 2 baje") == "roman"
    assert detect_script("कल 2 बजे") == "devanagari"
    assert detect_script("कल 2 बजे interview है") == "mixed"
    assert detect_script("") == "roman"
    assert mirror_script("कल 2 बजे interview है") == "devanagari"
    assert mirror_script("kal 2 baje interview है") == "roman"
    assert mirror_script("hello") == "roman"


def test_transliteration_handles_the_schwa() -> None:
    assert transliterate_word("कितना") == "kitna"
    assert transliterate_word("समझ") == "samajh"
    assert transliterate_word("कमरा") == "kamra"
    assert transliterate_word("शर्मा") == "sharma"


def test_reply_script_falls_back_to_roman_without_a_variant() -> None:
    assert to_script("some unregistered line", "devanagari") == "some unregistered line"
    assert to_script("anything", "roman") == "anything"
    register_variant("Test line ok", "टेस्ट लाइन")
    assert variant_for("Test  line ok") == "टेस्ट लाइन"
    assert to_script("Test line ok", "devanagari") == "टेस्ट लाइन"
    assert to_script("Test line ok", "roman") == "Test line ok"


def test_never_raises_on_odd_input() -> None:
    rng = random.Random(7)
    pool = [chr(c) for c in range(0x0900, 0x0980)] + list(" ,.!?₹%0123456789abc\n\t-")
    for _ in range(300):
        text = "".join(rng.choice(pool) for _ in range(rng.randint(0, 40)))
        n = normalise_text(text)
        assert isinstance(n.text, str) and n.original == text
    assert normalise_text("ा्ंँ").original == "ा्ंँ"
    assert normalise_text(" " * 5).text == " " * 5
