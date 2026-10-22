"""The labelled Devanagari / mixed-script set and its accuracy report command."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from friday.cli import main
from friday.lang_dev.evaluate import INTENTS, evaluate, load_cases


def test_the_set_is_big_enough_and_has_a_held_out_part() -> None:
    cases = load_cases("all")
    held = load_cases("heldout")
    assert len(cases) >= 250
    assert len(held) >= 80
    assert {c.intent for c in cases} <= set(INTENTS)
    for intent in ("call", "card_question", "add_card", "bill", "event", "stop_delete", "menu"):
        assert sum(c.intent == intent for c in cases) >= 6, intent
    # no message is in both parts
    assert not {c.text for c in load_cases("dev")} & {c.text for c in held}
    assert all(c.text.strip() for c in cases)


def test_every_message_uses_devanagari_or_is_a_labelled_control() -> None:
    from friday.lang_dev.normalise import detect_script

    plain = [c for c in load_cases("all") if detect_script(c.text) == "roman"]
    assert len(plain) <= 12, "the set is about Devanagari and mixed script"


def test_accuracy_gate_dev_and_heldout() -> None:
    dev = evaluate(load_cases("dev"))
    held = evaluate(load_cases("heldout"))
    assert dev.intent_acc >= 0.95, dev.failures()[:3]
    # a regression gate, not a claim: the held-out numbers are in docs/VOICE_NOTES_AND_DEVANAGARI.md
    assert held.intent_acc >= 0.90, held.failures()[:3]
    assert held.strict_acc >= 0.85


def test_the_normaliser_is_what_makes_it_work() -> None:
    cases = load_cases("heldout")
    with_it = evaluate(cases)
    without = evaluate(cases, normalise=False)
    assert with_it.intent_acc - without.intent_acc > 0.5


def test_command_prints_per_intent_accuracy_and_failures() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["chatbot", "devanagari-eval", "--split", "heldout", "--baseline"])
    out = buf.getvalue()
    assert code == 0
    assert "with the normaliser (heldout)" in out
    assert "without it (heldout)" in out
    assert "event" in out and "strict acc" in out and "ALL" in out
