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


def test_known_gaps_are_reported_but_not_counted():
    outcomes = R.evaluate_all(("emergency_words",))
    gaps = [o for o in outcomes if o.known_gap]
    assert gaps and R.metrics(outcomes)["emergency_words"]["known_gaps"] == len(gaps)
    assert R.metrics(outcomes)["emergency_words"]["scenarios"] == len(outcomes) - len(gaps)


def test_ids_are_unique_per_category():
    outcomes = R.evaluate_all()
    ids = [(o.category, o.id) for o in outcomes]
    assert len(ids) == len(set(ids))
