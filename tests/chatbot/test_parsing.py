"""Reading names, cities, languages, places and commands out of what people type."""

from __future__ import annotations

import pytest

from friday.chatbot import commands as c


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Rahul", "Rahul"),
        ("rahul sharma", "Rahul Sharma"),
        ("mera naam Rahul hai", "Rahul"),
        ("my name is Asha", "Asha"),
        ("I am Asha", "Asha"),
        ("राहुल", "राहुल"),
        ("मेरा नाम राहुल है", "राहुल"),
        ("hi", None),
        ("hello", None),
        ("haan", None),
        ("mummy ko call karo", None),
        ("kya naam hai tumhara?", None),
        ("12345", None),
        ("", None),
        ("a b c d e", None),
    ],
)
def test_parse_name(text, want):
    assert c.parse_name(text) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Pune", "Pune"),
        ("main Pune mein hoon", "Pune"),
        ("Mumbai me", "Mumbai"),
        ("navi mumbai", "Navi Mumbai"),
        ("पुणे", "पुणे"),
        ("110001", None),
        ("kya kar rahe ho", None),
        ("menu", None),
    ],
)
def test_parse_city(text, want):
    assert c.parse_city(text) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("hindi", "hi"),
        ("Hinglish", "hinglish"),
        ("english", "en"),
        ("हिंदी", "hi"),
        ("mujhe english mein baat karni hai", "en"),
        ("kuch bhi", None),
    ],
)
def test_parse_language(text, want):
    assert c.parse_language(text) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("ghar", ("Home", ["ghar", "home"])),
        ("Office", ("Office", ["office", "kaam"])),
        ("घर", ("Home", ["ghar", "home"])),
        ("ऑफिस", ("Office", ["office", "kaam"])),
        ("mummy ka ghar", ("Mummy Ka Ghar", ["mummy ka ghar"])),
        ("kya hai yeh?", None),
        ("", None),
    ],
)
def test_parse_place_label(text, want):
    assert c.parse_place_label(text) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [("mummy", "mummy"), ("Bhaiya", "Bhaiya"), ("मम्मी", "मम्मी"), ("Rakesh uncle", "Rakesh uncle")],
)
def test_parse_nickname(text, want):
    assert c.parse_nickname(text) == want


@pytest.mark.parametrize("text", ["kal subah 9 baje meeting hai", "kya?", "a b c d", "hello", "12"])
def test_parse_nickname_refuses_what_is_not_one(text):
    assert c.parse_nickname(text) is None


@pytest.mark.parametrize(
    ("text", "want"),
    [("card", "card"), ("Mera din", "day"), ("kisi ko call", "call"), ("din", "day")],
)
def test_parse_win_takes_only_the_button_words(text, want):
    assert c.parse_win(text) == want
    assert c.parse_win("mummy ko call karo ki main late hoon") is None
    assert c.parse_win("mera din kaisa hai aaj") is None


@pytest.mark.parametrize(
    ("pattern", "yes", "no"),
    [
        (
            c.MENU,
            ["menu", "Help", "kya kar sakti ho", "what can you do"],
            ["help me book", "menu card"],
        ),
        (c.STOP, ["stop", "Band karo", "unsubscribe"], ["stop calling", "band karo yeh call"]),
        (
            c.DELETE_ALL,
            ["delete everything", "sab delete karo", "mera data delete karo"],
            ["delete dentist"],
        ),
        (c.RESUME, ["start", "chalu karo"], ["start the call"]),
        (c.YES, ["haan", "Haan, theek hai", "ok", "yes", "हाँ"], ["haan lekin"]),
        (c.NO, ["nahi", "no", "nope", "नहीं"], ["nahi pata"]),
    ],
)
def test_commands_match_whole_short_messages_only(pattern, yes, no):
    for t in yes:
        assert pattern.match(c.norm(t)), t
    for t in no:
        assert not pattern.match(c.norm(t)), t


def test_human_takes_an_optional_reason():
    assert c.HUMAN.match("human")
    m = c.HUMAN.match(c.norm("human: mera call nahi laga"))
    assert m is not None and m.group("rest") == "mera call nahi laga"
    assert not c.HUMAN.match("human beings are strange")
