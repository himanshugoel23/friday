# ruff: noqa: E501
from __future__ import annotations

import pytest

from friday.receptionist import sim
from friday.receptionist.models import Urgency


def test_at_least_thirty_scripted_callers_with_all_the_required_kinds():
    cs = sim.callers()
    assert len(cs) >= 30
    ids = {c.id for c in cs}
    assert len({c.language for c in cs}) == 3  # Hindi (script), Hinglish and English
    kinds = ("spam-", "family-", "courier", "doctor", "wrong-number", "abusive", "silence")
    for k in kinds:
        assert any(k in i for i in ids), k
    assert len(ids) == len(cs)  # unique ids


@pytest.fixture(scope="module")
def results():
    import asyncio

    return asyncio.run(sim.run_all())


def test_every_caller_passes_all_invariants_and_expectations(results):
    bad = [(r.caller.id, r.problems) for r in results if not r.ok]
    assert bad == []


def test_nothing_is_longer_than_ninety_seconds(results):
    assert max(r.seconds for r in results) <= 90


def test_urgent_callers_are_pushed_once_and_nobody_else(results):
    for r in results:
        urgent = r.urgency == Urgency.URGENT.value
        assert r.pushes == (1 if urgent else 0), r.caller.id


def test_no_spoken_line_outside_the_registry(results):
    from friday.receptionist import lines

    allowed = set(lines.LINES) | {"readback"}
    for r in results:
        for key, _ in r.spoken:
            assert key in allowed, (r.caller.id, key)


def test_table_and_command(capsys):
    import argparse

    ns = argparse.Namespace(show=None, morning=True, cmd="receptionist-sim")
    assert sim.run_command(ns) == 0
    out = capsys.readouterr().out
    assert "callers passed" in out and "morning digest" in out and "short spoken version" in out
    ns2 = argparse.Namespace(show="spam-loan-hinglish", morning=False, cmd="receptionist-sim")
    assert sim.run_command(ns2) == 0
    assert "friday [greet.intro]" in capsys.readouterr().out
