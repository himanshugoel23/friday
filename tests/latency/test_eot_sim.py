# ruff: noqa: E501
"""The end-of-turn simulation on the held-out sentences: deterministic, and it reports what it should."""

from __future__ import annotations

from friday.latency.eot_sim import default_detector, format_report, simulate
from friday.learning.eot_train import load_gold


def test_simulation_is_deterministic_and_reports_cut_rates_and_added_delay():
    _train, test = load_gold()
    det, label = default_detector()
    a = simulate(test, det, mode="rest", extend_ms=700, median_ms=700)
    b = simulate(test, det, mode="rest", extend_ms=700, median_ms=700)
    assert a == b and "model" in label
    assert a.finished_n + a.unfinished_n == len(test)
    # the extension can only reduce the cut rate, and never below the "extend everything" oracle
    assert a.cut_rate_oracle <= a.cut_rate_semantic <= a.cut_rate_today
    assert a.cut_rate_semantic < a.cut_rate_today  # it helps on the unfinished sentences
    assert 0 <= a.mean_wasted_ms < 100  # few finished turns are wrongly extended
    assert a.extended_unfinished > 0.5


def test_a_longer_extension_cuts_fewer_turns_and_costs_no_more_on_finished_turns_than_its_size():
    _train, test = load_gold()
    det, _ = default_detector()
    short = simulate(test, det, extend_ms=300)
    long = simulate(test, det, extend_ms=1200)
    assert long.cut_rate_semantic <= short.cut_rate_semantic
    assert long.mean_wasted_ms >= short.mean_wasted_ms


def test_streaming_mode_only_applies_the_veto_so_the_commit_does_not_move():
    _train, test = load_gold()
    det, _ = default_detector()
    r = simulate(test, det, mode="stream")
    assert r.mean_commit_delta_ms == 0 and r.cut_rate_semantic == r.cut_rate_today


def test_report_text_names_its_assumption():
    _train, test = load_gold()
    text = format_report(test)
    assert "assumption" in text and "rules only" in text and "rules + model" in text
