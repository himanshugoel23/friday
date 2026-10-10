"""Dry runs: the real call runner + engine against simulated salons, scored, baselined."""

# ruff: noqa: E501

from __future__ import annotations

import json
import re

import pytest

from friday.cli import main as friday_main
from friday.core.models import Speaker
from friday.playbooks import dryrun
from friday.playbooks.dryrun import (
    CHECKS,
    LineMatcher,
    build_brief,
    load_personas,
    run_dryrun,
    run_persona,
)
from friday.playbooks.model import get_playbook

REQUESTED = {
    # price check (quote_only) and the usual salon behaviours
    "quote_friendly", "quote_busy_call_later", "quote_puts_on_hold", "quote_hold_too_long",
    "quote_asks_who_after_intro", "quote_pure_hindi", "quote_noisy_then_clear", "quote_rude_hangs_up",
    "quote_dnc_request", "quote_asks_customer_phone", "quote_wrong_number_later", "quote_asks_otp",
    "quote_one_service", "quote_two_services", "quote_three_services", "quote_ampersand_name",
    "quote_book_mode_without_delegation", "quote_price_depends", "quote_salon_raises_advance",
    # AI on request, in several phrasings and at several steps
    "ai_robot_at_identity", "ai_ho_at_identity", "ai_insaan_at_price", "ai_real_person_english",
    "ai_bot_english", "ai_computer_recorded", "ai_asked_twice", "ai_asked_at_slot_step",
    "ai_asked_at_fallback_step", "ai_asked_then_hangs_up",
    # book mode: the delegated close, the fallback day accepted / refused, nothing free
    "book_free_today", "book_busy_fallback_accepted", "book_busy_fallback_refused",
    "book_busy_fallback_nothing", "book_busy_no_fallback_other_time", "book_price_over_ceiling",
    "book_advance_with_slot", "book_yes_without_time", "book_stylist_pref",
    "says_yes_then_hangs_up_during_intro", "silent_after_identity",
}


@pytest.fixture(scope="module")
def report():
    import asyncio

    return asyncio.run(run_dryrun("salon_booking"))


def test_every_requested_persona_exists():
    ids = {p.id for p in load_personas("salon_booking").personas}
    assert ids >= REQUESTED


def test_all_personas_reach_their_expected_outcome_with_no_safety_violation(report):
    assert report.runs and report.safety_violations == []
    for r in report.runs:
        assert r.checks["reached_outcome"], r.persona
        assert r.checks["expected_outcome"], (r.persona, r.details["expected_outcome"])
        assert r.checks["no_unhandled_intent"], (r.persona, r.unhandled)
        assert r.checks["within_limits"], (r.persona, r.details["within_limits"])
        assert r.checks["fixed_lines_prerendered"], r.persona
        assert r.score == 1.0, (r.persona, r.failed)


def test_scoring_fields_are_filled(report):
    friendly = next(r for r in report.runs if r.persona == "quote_friendly")
    assert friendly.outcome == "QUOTE_COLLECTED" and friendly.call_outcome == "partial"
    assert friendly.steps == ["S0", "S3", "S7q"]  # who+why+price, then the one-line close
    assert friendly.turns == 3 and 15 < friendly.seconds < 120
    assert friendly.llm_calls == 0 and friendly.repeats == 0 and friendly.safety == []
    hold = next(r for r in report.runs if r.persona == "quote_puts_on_hold")
    assert hold.repeats >= 1 and hold.seconds > friendly.seconds  # waited, then asked again
    over = next(r for r in report.runs if r.persona == "book_over_budget_negotiates")
    assert "S3b" in over.steps
    quiet = next(r for r in report.runs if r.persona == "quote_over_budget_never_haggles")
    assert "S3b" not in quiet.steps  # a price check never asks for a discount
    rude = next(r for r in report.runs if r.persona == "quote_rude_hangs_up")
    assert rude.outcome == "REFUSED" and rude.turns <= 3
    wrong = next(r for r in report.runs if r.persona == "quote_wrong_number_later")
    assert wrong.outcome == "WRONG_NUMBER"
    fb = next(r for r in report.runs if r.persona == "book_busy_fallback_accepted")
    assert fb.steps == ["S0", "S3", "S2", "S2f", "S7"] and fb.outcome == "BOOKED"


def test_special_outcomes(report):
    by = {r.persona: r for r in report.runs}
    assert by["book_free_today"].outcome == "BOOKED" and by["book_free_today"].call_outcome == "success"
    assert by["book_busy_fallback_accepted"].outcome == "BOOKED"
    assert by["book_busy_fallback_refused"].outcome == "SLOT_OFFERED"  # never books another time
    assert by["book_price_over_ceiling"].outcome == "SLOT_OFFERED"
    assert by["book_advance_with_slot"].outcome == "SLOT_OFFERED"  # even with a delegation
    assert by["quote_book_mode_without_delegation"].outcome == "QUOTE_COLLECTED"
    assert by["quote_hold_too_long"].call_outcome == "hold_timeout"
    assert by["quote_never_clear"].outcome == "UNCLEAR"
    assert by["quote_dnc_request"].outcome == "REFUSED"
    assert not any(r.outcome == "BOOKED" for p, r in by.items() if p.startswith("quote_"))


def test_hinglish_only_in_every_simulated_call(report):
    names = ["लुक्स", "श्रेया", "हिमांशु", "रवि", "सन्स"]  # names are read in Devanagari on purpose
    for r in report.runs:
        for speaker, text in r.transcript:
            if speaker == Speaker.FRIDAY.value:
                bare = text
                for n in names:
                    bare = bare.replace(n, "")
                assert not re.search(r"[ऀ-ॿ]", bare), (r.persona, text)


def test_every_friday_utterance_is_made_only_of_playbook_lines(report):
    pb = get_playbook("salon_booking")
    m = LineMatcher(pb, dryrun._runner_lines(pb))
    for r in report.runs:
        for speaker, text in r.transcript:
            if speaker == Speaker.FRIDAY.value:
                _ids, left = m.split(text)
                assert left == "", (r.persona, text, left)


def test_table_lists_every_scenario_and_the_columns(report):
    table = dryrun.render_table(report)
    for col in ("outcome", "steps", "turns", "secs", "rep", "unh", "safe", "score"):
        assert col in table
    for r in report.runs:
        assert r.persona in table
    assert "TOTAL" in table and "100%" in table


async def test_scenarios_filter():
    rep = await run_dryrun("salon_booking", only=["hold", "rude"])
    assert {r.persona for r in rep.runs} == {"quote_puts_on_hold", "quote_hold_too_long", "quote_rude_hangs_up"}


# ------------------------------------------------------------------ baseline
def test_baseline_roundtrip_and_regression_detection(report, tmp_path):
    path = tmp_path / "b.json"
    dryrun.save_baseline(report, path)
    base = dryrun.load_baseline("salon_booking", path)
    assert base["version"] == 1 and set(base["scenarios"]) == {r.persona for r in report.runs}
    assert dryrun.find_regressions(report, base) == []
    first = report.runs[0]
    first.checks["expected_outcome"] = False  # something got worse
    try:
        problems = dryrun.find_regressions(report, base)
    finally:
        first.checks["expected_outcome"] = True
    assert problems and first.persona in problems[0] and "expected_outcome" in problems[0]
    table = dryrun.render_table(report, base)
    assert "same" in table


def test_shipped_baseline_matches_the_current_behaviour(report):
    base = dryrun.load_baseline("salon_booking")
    assert base is not None, "run: uv run friday playbook dry-run salon_booking --update-baseline"
    assert dryrun.find_regressions(report, base) == []
    assert set(base["scenarios"]) == {r.persona for r in report.runs}


# ------------------------------------------------------------------ CLI
def test_cli_dry_run_ok_and_baseline_flow(tmp_path, capsys):
    b = tmp_path / "base.json"
    assert friday_main(["playbook", "dry-run", "salon_booking", "--scenarios", "quote_friendly",
                        "--baseline", str(b), "--update-baseline"]) == 0
    assert b.exists()
    assert friday_main(["playbook", "dry-run", "salon_booking", "--scenarios", "quote_friendly",
                        "--baseline", str(b), "--show", "quote_friendly"]) == 0
    out = capsys.readouterr().out
    assert "quote_friendly" in out and "Transcript" in out and "virtual assistant" in out


def test_cli_exit_code_is_nonzero_on_a_safety_violation(monkeypatch, capsys):
    from friday.playbooks.engine import PlaybookPolicy

    real = PlaybookPolicy._say

    def leaky(self, c, text):
        return real(self, c, text + " Apna OTP bata dijiye.")

    monkeypatch.setattr(PlaybookPolicy, "_say", leaky)
    rc = friday_main(["playbook", "dry-run", "salon_booking", "--scenarios", "quote_friendly"])
    out = capsys.readouterr().out
    assert rc == 2 and "SAFETY VIOLATION" in out and "OTP" in out


def test_cli_exit_code_is_nonzero_when_a_check_regresses(monkeypatch, tmp_path, capsys):
    b = tmp_path / "base.json"
    assert friday_main(["playbook", "dry-run", "salon_booking", "--scenarios", "quote_friendly",
                        "--baseline", str(b), "--update-baseline"]) == 0
    data = json.loads(b.read_text())
    data["scenarios"]["quote_friendly"]["checks"]["no_unhandled_intent"] = True
    b.write_text(json.dumps(data))
    from friday.playbooks.engine import PlaybookPolicy

    real = PlaybookPolicy._apply

    def worse(self, c, u, reply):
        c.st.unhandled.append("S3:TEST")
        return real(self, c, u, reply)

    monkeypatch.setattr(PlaybookPolicy, "_apply", worse)
    rc = friday_main(["playbook", "dry-run", "salon_booking", "--scenarios", "quote_friendly",
                      "--baseline", str(b)])
    assert rc == 1 and "REGRESSION" in capsys.readouterr().out


def test_cli_list_and_validate(tmp_path, capsys, raw):
    assert friday_main(["playbook", "list"]) == 0
    assert "salon_booking" in capsys.readouterr().out
    assert friday_main(["playbook", "validate", "salon_booking"]) == 0
    assert "OK" in capsys.readouterr().out
    bad = tmp_path / "bad.yaml"
    raw["lines"]["s4_ask"] = "Apna OTP batao"
    import yaml

    bad.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    assert friday_main(["playbook", "validate", str(bad)]) == 2
    assert "OTP" in capsys.readouterr().out
    assert friday_main(["playbook", "validate", "no_such_playbook"]) == 2
    assert friday_main(["playbook", "dry-run", "no_such_playbook"]) in (1, 2)


async def test_through_the_fake_llm_brain_gives_the_same_outcomes(report):
    rep = await run_dryrun("salon_booking", via_brain=True)
    assert rep.safety_violations == []
    want = {r.persona: r.outcome for r in report.runs}
    assert {r.persona: r.outcome for r in rep.runs} == want
    # one model call per salon reply at most (hold/silence/stop need none)
    for r in rep.runs:
        assert r.llm_calls <= r.turns


async def test_a_persona_can_be_run_alone():
    pb = get_playbook("salon_booking")
    pf = load_personas("salon_booking")
    persona = next(p for p in pf.personas if p.id == "ai_insaan_at_price")
    brief = build_brief(pb, pf, persona)
    assert brief.playbook == "salon_booking"
    assert brief.disclosure().startswith("Hello, kya meri baat")
    assert brief.ai_disclosure == "on_request" and brief.redisclosure_text
    assert brief.playbook_inputs["playbook_mode"] == "quote_only"
    r = await run_persona(pb, pf, persona)
    assert r.outcome == "QUOTE_COLLECTED"
    assert any("personal AI assistant" in t for k, t in r.transcript if k == "friday")


def test_checks_constant_lists_the_scored_checks():
    assert "no_safety_violation" in CHECKS and "fixed_lines_prerendered" in CHECKS


def test_cli_paths_and_saved_redacted_transcripts(tmp_path, capsys):
    rc = friday_main(["playbook", "dry-run", "salon_booking", "--scenarios", "quote_friendly,quote_asks_otp",
                      "--paths", "--save-transcripts", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc in (0, 1) and "S0 > S3 > S7q" in out
    data = json.loads((tmp_path / "salon_booking-dryrun.json").read_text(encoding="utf-8"))
    assert data["simulated"] is True and {r["persona"] for r in data["runs"]} == {
        "quote_friendly", "quote_asks_otp"}
    otp = next(r for r in data["runs"] if r["persona"] == "quote_asks_otp")
    assert any(
        t["speaker"] == "friday" and t["text"].startswith("Hello") for t in otp["transcript"]
    )


async def test_repeated_holds_are_limited():
    from .conftest import drive, make_brief

    replies = ["Haan boliye"] + ["Ek minute hold kijiye"] * 6
    run = await drive(replies, brief=make_brief())
    from friday.core.models import CallActionType

    assert sum(a.type == CallActionType.WAIT_ON_HOLD for a in run.actions) <= 3
