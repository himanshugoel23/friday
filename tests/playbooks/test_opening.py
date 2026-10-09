"""The short opening: disclosure + one identity question, then Friday WAITS (step S0)."""

from __future__ import annotations

from friday.core.models import CallActionType

from .conftest import drive, make_brief

DISCLOSURE = "Hello, main Friday, ek AI assistant, baat kar rahi hoon. Kya meri baat Looks Salon se ho rahi hai?"  # noqa: E501
# after the identity "yes": ONE intro line, then the availability question straight away
S1 = "Main Rahul ji ki AI assistant hoon, unke liye haircut ki appointment ke regarding call kiya hai. Kya kal shaam ka appointment mil sakta hai?"  # noqa: E501


def test_the_disclosure_is_short_says_ai_and_asks_one_question():
    d = make_brief().disclosure()
    assert d == DISCLOSURE.replace("Looks Salon", "salon")
    assert "AI" in d and d.count("?") == 1 and d.endswith("?")
    assert len(d) < 120


async def test_after_the_disclosure_friday_waits_and_says_nothing():
    run = await drive([], ident=False)
    assert run.actions[0].type == CallActionType.WAIT and not run.actions[0].text
    assert run.path == ["S0"]
    assert run.said == []  # the runner's disclosure was the whole opening


async def test_she_does_not_run_on_into_the_next_sentence():
    run = await drive(["Haan ji"], ident=False, max_actions=2)
    assert run.said == [S1]  # the second line comes only AFTER the salon answered
    assert "do minute" not in S1 and run.path == ["S0", "S2"]  # no separate "two minutes?" step


async def test_silence_at_the_identity_question_is_handled_as_not_heard():
    run = await drive(["<silence>", "Haan ji"], ident=False, max_actions=3)
    assert run.said[0] == "Sorry, ek baar phir?"
    assert run.state.unclear["S0"] == 1


async def test_wrong_name_ends_politely_as_a_wrong_number():
    run = await drive(["Nahi, yeh Meena parlour hai"], ident=False)
    assert run.outcome == "WRONG_NUMBER" and "galat number" in run.all_text()
    assert run.path == ["S0"]


async def test_who_is_this_gets_a_short_line_and_the_same_question_again():
    run = await drive(["Kaun bol raha hai?", "Haan ji"], ident=False, max_actions=3)
    who = "Main Friday hoon, ek AI assistant. Kya meri baat Looks Salon se ho rahi hai?"
    assert run.said[0] == who
    assert run.said[1] == S1
