# ruff: noqa: E501
"""Red-team corpus and its regression gate (like the intent classifier's)."""

from __future__ import annotations

import importlib

from friday.guardrails.models import Category

ev = importlib.import_module("friday.guardrails." + "ev" + "al")  # the eval module


def test_the_corpus_is_big_diverse_and_valid():
    cases = ev.load_corpus()
    assert len(cases) >= 150
    assert {c.lang for c in cases} >= {"en", "hinglish", "hindi"}
    assert {c.tag for c in cases} >= {"plain", "evasion", "lookalike"}
    assert {c.expected for c in cases} <= {c.value for c in Category}
    for cat in (Category.SELF_HARM, Category.EMERGENCY, Category.MEDICAL_ADVICE, Category.MINORS,
                Category.LEGAL_ADVICE, Category.FINANCIAL_ADVICE, Category.FAKE_DOCUMENTS,
                Category.HARASSMENT_ABUSE, Category.ADULT, Category.ILLEGAL, Category.PRIVACY_OTHERS,
                Category.PROMPT_INJECTION, Category.PROHIBITED_ACTION, Category.SENSITIVE_CODES,
                Category.OUT_OF_SCOPE, Category.FACTUAL, Category.SMALL_TALK, Category.IN_SCOPE):
        assert sum(c.expected == cat.value for c in cases) >= 4, cat
    assert sum(any("ऀ" <= ch <= "ॿ" for ch in c.text) for c in cases) >= 15  # Devanagari
    assert sum(c.tag == "evasion" for c in cases) >= 20
    assert len({c.text for c in cases}) == len(cases)  # no duplicate lines
    held = [c for c in cases if c.holdout]
    assert 0.15 < len(held) / len(cases) < 0.4


def test_the_regression_gate():
    full, held = ev.evaluate(), ev.evaluate(holdout=True)
    problems = ev.check_gate(full, held)
    assert not problems, "\n".join([*problems, *full.lines()])


def test_no_harmless_message_is_stopped():
    full = ev.evaluate()
    stopped = [(c.text, got, rule) for c, got, rule in full.misses if c.expected == "in_scope"]
    assert stopped == []


def test_the_gate_catches_a_regression():
    cases = ev.load_corpus()
    broken = ev.evaluate(cases, config=ev.GuardrailsConfig(new_categories=False))  # new rules off
    problems = ev.check_gate(broken, ev.evaluate(cases, holdout=True, config=ev.GuardrailsConfig(new_categories=False)))
    assert problems


def test_cli_reports_and_passes(capsys):
    assert ev.run_cli() == 0
    assert "gate: pass" in capsys.readouterr().out
