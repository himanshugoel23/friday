"""When a reply is spoken, when it is also text, when it is only text (pure rules)."""

from __future__ import annotations

import pytest

from friday.chatbot_media.policy import decide, estimated_seconds, is_approval, is_private
from friday.core.models import ReplyButton

SHORT = "Theek hai, ho gaya."
APPROVE = [
    ReplyButton(id="callap:r1:yes", title="Approve"),
    ReplyButton(id="callap:r1:edit", title="Edit"),
]


def test_mirror_speaks_only_after_a_voice_note() -> None:
    assert decide(SHORT, mode="mirror", user_spoke=True).speak
    d = decide(SHORT, mode="mirror", user_spoke=False)
    assert not d.speak and d.send_text and d.reason == "mirror_text_turn"


def test_text_mode_never_speaks_even_after_a_voice_note() -> None:
    d = decide(SHORT, mode="text", user_spoke=True)
    assert not d.speak and d.send_text


def test_voice_mode_speaks_a_typed_turn_too() -> None:
    assert decide(SHORT, mode="voice", user_spoke=False).speak


def test_plain_short_reply_is_voice_only() -> None:
    d = decide(SHORT, mode="mirror", user_spoke=True)
    assert d.speak and not d.send_text and d.reason == "voice_only"


@pytest.mark.parametrize(
    "text",
    [
        "Kal 2 baje ka interview likh liya.",  # a time is a number
        "Aapka bill ₹1,200 hai.",
        "Yeh dekho: https://example.com/pay",
        "Mail karo test@example.com par.",
        "Paanch sau rupaye ka hai.",
    ],
)
def test_numbers_amounts_and_links_also_go_as_text(text: str) -> None:
    d = decide(text, mode="mirror", user_spoke=True)
    assert d.speak and d.send_text, text


def test_buttons_always_also_go_as_text() -> None:
    d = decide(SHORT, [ReplyButton(id="led:1:used", title="Haan")], mode="mirror", user_spoke=True)
    assert d.speak and d.send_text


def test_an_approval_is_never_spoken() -> None:
    d = decide("Mummy ko call karun?", APPROVE, mode="both", user_spoke=True)
    assert not d.speak and d.send_text and d.reason == "approval_is_text"
    assert is_approval("x", APPROVE)
    assert is_approval("Please approve", [ReplyButton(id="b:1", title="Ok")])
    assert not is_approval("Please approve", [])  # no buttons: not an approval prompt
    for prefix in ("a:", "q:", "n:", "callact:"):
        assert is_approval("x", [ReplyButton(id=prefix + "1", title="Ok")])


def test_a_long_reply_is_text_only() -> None:
    long = "Yeh ek lamba jawab hai. " * 40
    d = decide(long, mode="voice", user_spoke=True, max_chars=600)
    assert not d.speak and d.send_text and d.reason == "too_long"
    assert estimated_seconds("x" * 600) == 30


@pytest.mark.parametrize(
    "text",
    [
        "HDFC Regalia se 4 paise bachenge.",
        "Aapka credit card bill kal due hai.",
        "Kal interview hai, shubhkaamnaayein.",
        "Dentist ka appointment yaad hai.",
        "Mummy ki dawai ka time ho gaya.",
    ],
)
def test_private_details_are_not_read_aloud_unless_asked_by_voice(text: str) -> None:
    assert is_private(text)
    typed = decide(text, mode="voice", user_spoke=False)
    assert not typed.speak and typed.reason == "private_not_read_aloud"
    assert decide(text, mode="voice", user_spoke=True).speak  # the user asked by voice


def test_both_mode_always_sends_the_text_too() -> None:
    d = decide(SHORT, mode="both", user_spoke=True)
    assert d.speak and d.send_text


def test_empty_reply_is_not_spoken() -> None:
    assert not decide("", mode="both", user_spoke=True).speak
    assert not decide(None, mode="both", user_spoke=True).speak


def test_the_maine_suna_check_is_text_even_in_both_mode() -> None:
    buttons = [ReplyButton(id="vn:ok", title="Haan, sahi"), ReplyButton(id="vn:no", title="Nahi")]
    d = decide('Maine suna: "x". Sahi hai?', buttons, mode="both", user_spoke=True)
    assert not d.speak and d.reason == "confirmation_is_text"
