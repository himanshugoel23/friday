# ruff: noqa: E501
"""T18 regression gate: the safety evaluation (tests/bench/robin) must not fall below the committed baseline.

Fails when recall on HIGH-risk scenarios, or overall recall, drops below tests/bench/robin/baseline.json, or when a false-positive rate rises,
or when the corpus shrinks. Only the lead updates the baseline. The negative controls prove the gate really fails when a rule is weakened.
The corpus is small, synthetic and unreviewed (docs/ROBIN_EVAL.md): unverified clinical/linguistic review needed. Fakes only, no network.
"""

from __future__ import annotations

import re

import pytest
import yaml

from tests.bench.robin import runner as R


@pytest.fixture(scope="module")
def baseline():
    return R.load_baseline()


def _gate(categories):
    out = R.evaluate_all(categories)
    return R.check_gate(
        R.metrics(out),
        {
            "categories": {
                c: v for c, v in R.load_baseline()["categories"].items() if c in categories
            }
        },
    )


def test_gate_holds_for_every_category(baseline):
    out = R.evaluate_all()
    m = R.metrics(out)
    assert set(baseline["categories"]) == set(R.CATEGORIES)
    assert R.check_gate(m, baseline) == []


def test_corpus_meets_the_ticket_minimums():
    sc = yaml.safe_load((R.SCEN / "scamcheck.yaml").read_text(encoding="utf-8"))["scenarios"]
    assert (
        len([s for s in sc if s["label"] == "scam"]) >= 40
        and len([s for s in sc if s["label"] == "benign"]) >= 20
    )
    assert {s["lang"] for s in sc} == {"en", "hinglish", "hi"}
    assert any(re.search("[ऀ-ॿ]", s["text"]) for s in sc)
    assert (
        len(yaml.safe_load((R.SCEN / "calls.yaml").read_text(encoding="utf-8"))["dialogues"]) >= 10
    )
    care = yaml.safe_load((R.SCEN / "care.yaml").read_text(encoding="utf-8"))["scenarios"]
    assert (
        len([c for c in care if c["expect"] == "NONE"]) >= 20
        and len([c for c in care if c["expect"] == "HIGH"]) >= 20
    )
    em = yaml.safe_load((R.SCEN / "emergency.yaml").read_text(encoding="utf-8"))
    assert any("madad" in w["text"] for w in em["words"]) and any(
        "bachao" in w["text"].lower() for w in em["words"]
    )
    assert any(f["hour"] < 5 for f in em["flow"])  # security paths are exercised at night


def test_gate_logic_pure():
    base = {
        "categories": {
            "x": {
                "scenarios": 4,
                "positives": 2,
                "negatives": 2,
                "high_positives": 1,
                "tp": 2,
                "fp": 0,
                "high_tp": 1,
            }
        }
    }
    good = {"x": {"scenarios": 4, "recall": 1.0, "recall_high": 1.0, "fp_rate": 0.0}}
    assert R.check_gate(good, base) == []
    assert R.check_gate({"x": {**good["x"], "recall_high": 0.0}}, base)
    assert R.check_gate({"x": {**good["x"], "recall": 0.5}}, base)
    assert R.check_gate({"x": {**good["x"], "fp_rate": 0.5}}, base)
    assert R.check_gate(
        {"x": {**good["x"], "scenarios": 3}}, base
    )  # deleting scenarios is not a way to pass
    assert R.check_gate({}, base)


# ------------------------------------------------------------------ negative controls: weaken a rule, the gate MUST fail
def test_negative_control_scamcheck_otp_rule_weakened(monkeypatch):
    from friday.robindevice import scamcheck as S

    assert _gate(("scamcheck",)) == []
    monkeypatch.setattr(S, "SENSITIVE", re.compile(r"(?!x)x"))  # OTP/PIN never recognised
    bad = _gate(("scamcheck",))
    assert any("HIGH-risk recall" in b for b in bad), bad


def test_negative_control_scamcheck_threshold_raised(monkeypatch):
    from friday.robindevice import scamcheck as S

    monkeypatch.setattr(S, "SCAM_LIKELY_AT", 99)
    monkeypatch.setattr(S, "RISKY_AT", 99)
    assert _gate(("scamcheck",))


def test_negative_control_scamcheck_false_positives_rise(monkeypatch):
    from friday.robindevice import scamcheck as S

    monkeypatch.setattr(S, "RISKY_AT", 0)  # everything becomes RISKY
    bad = _gate(("scamcheck",))
    assert any("false-positive rate" in b for b in bad), bad


def test_negative_control_callpattern_high_tier_unreachable(monkeypatch):
    from friday.robindevice import callpattern as C

    monkeypatch.setitem(C.TIER_AT, "HIGH", 999)
    bad = _gate(("callpattern",))
    assert any("HIGH-risk recall" in b for b in bad), bad


def test_negative_control_care_detector_blind(monkeypatch):
    from friday.care import detect as D

    monkeypatch.setattr(D, "HIGH", [])
    bad = _gate(("care",))
    assert any("HIGH-risk recall" in b for b in bad), bad


def test_negative_control_sos_words_dropped(monkeypatch):
    from friday.robin import answers as A

    monkeypatch.setattr(A, "HELP", ("zzz",))
    bad = _gate(("emergency_words",))
    assert any("HIGH-risk recall" in b for b in bad), bad


def test_negative_control_ladder_changed(monkeypatch):
    from friday.robin import alerts as AL

    real = AL.plan_for
    monkeypatch.setattr(
        AL, "plan_for", lambda *a, **k: [s for s in real(*a, **k) if s["action"] != "call_child"]
    )
    assert _gate(("emergency_ladder",))
