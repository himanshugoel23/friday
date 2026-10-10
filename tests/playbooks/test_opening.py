"""The opening (founder v6): Friday first asks ONLY "kya meri baat X se ho rahi hai?", waits, and on
the salon's yes says in ONE turn who she is (a "virtual assistant": no AI unless asked), why she
calls and asks the price. The business name is read in Devanagari (names pipeline)."""

# ruff: noqa: E501

from __future__ import annotations

import re

from friday.core.models import CallActionType

from .conftest import drive, make_brief

NAME = "लुक्स saloon"  # "Looks Salon": override for Looks + the glossary's saloon
OPENING = f"Hello, kya meri baat {NAME} se ho rahi hai?"
WHO = "Main Friday baat kar rahi hoon, Rahul sir ki virtual assistant."
WHY_QUOTE = "Rahul sir ko haircut karwana hai, toh uske charges ke regarding call kiya hai."
WHY_BOOK = "Rahul sir ko haircut karwana hai, toh unki booking ke regarding call kiya hai."
PRICE_Q = "Toh sir, ek baar bata sakte hain inke kya charges rahenge?"
S1 = f"{WHO} {WHY_QUOTE} {PRICE_Q}"


def test_the_opening_is_only_an_identity_question():
    d = make_brief().disclosure()
    assert d == OPENING
    assert d.count("?") == 1 and d.endswith("?") and len(d) < 60
    assert not re.search(r"AI|Rahul|haircut|appointment|booking|price|virtual", d)  # nothing else


async def test_after_the_opening_friday_waits_and_says_nothing():
    run = await drive([], ident=False)
    assert run.actions[0].type == CallActionType.WAIT and not run.actions[0].text
    assert run.path == ["S0"]
    assert run.said == []  # the runner's opening was the whole first turn


async def test_on_yes_one_turn_says_who_why_and_the_price_question_but_not_ai():
    for yes in ("Haan ji", "Boliye", "Haan boliye", "Ji bataiye"):
        run = await drive([yes], ident=False, max_actions=2)
        assert run.said == [S1], yes
        assert "AI" not in run.said[0] and "virtual assistant" in run.said[0]  # on request only
        assert run.path == ["S0", "S3"]
    assert S1.count("?") == 1 and S1.endswith("kya charges rahenge?")
    assert not re.search(r"do minute|two minute|time hai|slot|kitne baje", S1)


async def test_book_mode_intro_says_booking_and_the_price_still_comes_first():
    run = await drive(["Haan ji"], ident=False, max_actions=2, brief=make_brief(book=True))
    assert run.said == [f"{WHO} {WHY_BOOK} {PRICE_Q}"]


async def test_the_recording_notice_is_between_who_and_why_when_recording_is_on():
    from friday.playbooks.engine import PlaybookPolicy

    run = await drive(["Haan ji"], ident=False, max_actions=2, policy=PlaybookPolicy(recording=True))
    assert run.said[0].startswith(f"{WHO} Yeh call quality ke liye record ho sakta hai. {WHY_QUOTE}")


async def test_the_price_answer_closes_a_price_check():
    run = await drive(["Haircut 400 rupaye, 30 minute"], brief=make_brief())
    assert run.said[0] == S1
    assert run.said[1] == "Theek hai sir, main Rahul sir ko bata deti hoon. Thank you."
    assert run.outcome == "QUOTE_COLLECTED"


async def test_silence_at_the_identity_question_is_handled_as_not_heard():
    run = await drive(["<silence>", "Haan ji"], ident=False, max_actions=3)
    assert run.said[0] == "Sorry, ek baar phir?" and run.said[1] == S1
    assert run.state.unclear["S0"] == 1


async def test_wrong_name_ends_politely_as_a_wrong_number_without_a_purpose():
    run = await drive(["Nahi, yeh Meena parlour hai"], ident=False)
    assert run.outcome == "WRONG_NUMBER" and "galat number" in run.all_text()
    assert run.path == ["S0"]
    assert not re.search(r"AI|virtual|appointment|haircut|Rahul|booking", run.all_text())


async def test_who_is_this_says_virtual_assistant_and_the_same_question_again():
    run = await drive(["Kaun bol raha hai?", "Haan ji"], ident=False, max_actions=3)
    assert run.said[0] == f"Main Friday hoon, Rahul sir ki virtual assistant. Kya meri baat {NAME} se ho rahi hai?"
    assert run.said[1] == S1
    rep = await drive(["Sorry, phir se boliye?"], ident=False, max_actions=2)
    assert rep.said[0] == run.said[0]


async def test_are_you_a_bot_at_the_identity_question_is_answered_truthfully_then_the_call_goes_on():
    bot = await drive(["Robot hai kya?"], ident=False, max_actions=2)
    assert bot.said[0].startswith("Haan ji, main Rahul sir ki personal AI assistant hoon.")
    assert bot.said[0].endswith(PRICE_Q) and "S3" in bot.path


async def test_the_honorific_and_names_are_inputs():
    b = make_brief(inputs={"honorific": "madam", "user_spoken": "राहुल", "business_name": "Shreya Salon",
                           "business_name_spoken": "श्रेया saloon"})
    assert b.disclosure() == "Hello, kya meri baat श्रेया saloon se ho rahi hai?"
    run = await drive(["Haan ji"], ident=False, max_actions=2, brief=b)
    assert run.said[0].startswith("Main Friday baat kar rahi hoon, राहुल madam ki virtual assistant.")
    assert "Rahul" not in run.said[0]  # the spoken form replaces the Roman one in speech
