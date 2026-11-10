# ruff: noqa: E501
"""The runner itself: it prints precision/recall per category and exits 0 when the baseline is met (fakes only)."""

from __future__ import annotations

from tests.bench.robin import __main__ as M
from tests.bench.robin import runner as R


def test_runner_prints_a_row_per_category(capsys):
    assert M.main(["--gate"]) == 0
    out = capsys.readouterr().out
    for cat in R.CATEGORIES:
        assert cat in out
    assert (
        "recall" in out and "prec" in out and "unverified clinical/linguistic review needed" in out
    )


def test_known_gaps_are_reported_but_not_counted(monkeypatch):
    """No known gap is left in the corpus (2026-11-10), so the mechanism is tested with one injected, deliberately unmet word."""
    real = R._load

    def with_gap(name):
        data = real(name)
        if name == "emergency.yaml":
            data = {**data, "words": [*data["words"], {"id": "injected_gap", "text": "zzz nothing here", "expect": "help", "known_gap": True}]}
        return data

    monkeypatch.setattr(R, "_load", with_gap)
    outcomes = R.evaluate_all(("emergency_words",))
    gaps = [o for o in outcomes if o.known_gap]
    assert [o.id for o in gaps] == ["injected_gap"] and R.metrics(outcomes)["emergency_words"]["known_gaps"] == 1
    assert R.metrics(outcomes)["emergency_words"]["scenarios"] == len(outcomes) - 1


def test_ids_are_unique_per_category():
    outcomes = R.evaluate_all()
    ids = [(o.category, o.id) for o in outcomes]
    assert len(ids) == len(set(ids))
