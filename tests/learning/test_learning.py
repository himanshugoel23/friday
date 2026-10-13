from __future__ import annotations

import argparse
import json
import threading

import pytest

from friday.learning import evaluate as ev
from friday.learning.fewshot import export_fewshot
from friday.learning.labels import Label, LabelError, add_label, load_labels
from friday.learning.log import mask_text, record_turn
from friday.learning.queue import normalise, top


def _rec(path, text, **kw):
    base = dict(call_id="CA123", playbook_id="pb", step="s", text=text, intent="UNCLEAR",
                confident=True, path=path)
    base.update(kw)
    return record_turn(**base)


def test_masking():
    assert mask_text("mera number 98765 43210 hai") == "mera number <phone> hai"
    assert mask_text("call +91-9876543210 now") == "call <phone> now"
    assert mask_text("otp 123456 hai") == "otp <num> hai"
    assert mask_text("rate 1500 lagega") == "rate 1500 lagega"
    assert "<email>" in mask_text("a.b@x.com bhejo")


def test_record_turn_writes_masked_hashed_line(tmp_path):
    p = tmp_path / "u.jsonl"
    assert _rec(p, "call 9876543210", unhandled=True, repeat_count=2)
    row = json.loads(p.read_text().splitlines()[0])
    assert row["text"] == "call <phone>"
    assert "CA123" not in json.dumps(row) and len(row["call_ref"]) == 16
    assert row["unhandled"] is True and row["repeat_count"] == 2
    assert {"ts", "playbook_id", "step", "intent", "confident", "source"} <= set(row)
    _rec(p, "x")
    assert json.loads(p.read_text().splitlines()[1])["call_ref"] == row["call_ref"]


def test_record_turn_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert _rec(blocker / "sub" / "u.jsonl", "hi") is False


def test_record_turn_thread_safe(tmp_path):
    p = tmp_path / "u.jsonl"
    ts = [threading.Thread(target=lambda: [_rec(p, "haan") for _ in range(20)]) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(p.read_text().splitlines()) == 160


def test_queue_grouping_and_ranking(tmp_path):
    p = tmp_path / "u.jsonl"
    assert normalise("Rate 500, lagega!") == normalise("rate 700 lagega")
    for _ in range(5):
        _rec(p, "Haan ji!")
    _rec(p, "kuch alag baat", confident=False)
    _rec(p, "kuch alag baat", confident=False)
    _rec(p, "parking hai?", unhandled=True)
    rows = top(10, p)
    assert [r.key for r in rows] == ["parking hai", "kuch alag baat", "haan ji"]
    assert rows[1].count == 2 and rows[1].low_confidence == 2
    assert top(1, p)[0].unhandled == 1
    assert top(5, tmp_path / "missing.jsonl") == []


def test_label_validation(tmp_path):
    p = tmp_path / "l.yaml"
    p.write_text("# c\n- {text: a, intent: \"NO\"}\n", encoding="utf-8")
    with pytest.raises(LabelError):
        add_label("kuch", "NOT_AN_INTENT", path=p)
    with pytest.raises(LabelError):
        add_label("a", "NO", path=p)  # duplicate
    add_label("nahi sir", "NO", "note", path=p)
    labels = load_labels(p)
    assert [lb.intent for lb in labels] == ["NO", "NO"]
    assert labels[1].note == "note" and p.read_text().startswith("# c")


def test_cli_label_refuses_unknown_intent(tmp_path, monkeypatch):
    from friday.learning import cli, labels

    monkeypatch.setattr(labels, "LABELS_PATH", tmp_path / "l.yaml")
    ns = argparse.Namespace(learn_cmd="label", text="x", intent="BOGUS", note="")
    assert cli.run(ns) == 2


def test_evaluation_and_regression(tmp_path):
    good = [Label("haan ji bilkul", "YES"), Label("nahi sir", "NO")]
    rep = ev.evaluate(good)
    assert rep.accuracy == 100.0 and not rep.mistakes
    bp = tmp_path / "b.json"
    ev.save_baseline(rep, bp)
    base = ev.load_baseline(bp)
    assert ev.regressions(rep, base) == []
    worse = ev.evaluate([Label("haan ji bilkul", "YES"), Label("nahi sir", "YES")])
    assert worse.mistakes[0]["expected"] == "YES"
    base = {**base, "per_intent": {"YES": 100.0}}
    reasons = ev.regressions(worse, base)
    assert any(r.startswith("overall") for r in reasons)
    assert any(r.startswith("YES:") for r in reasons)
    assert ev.regressions(rep, None) == []
    # within tolerance is fine
    assert ev.regressions(rep, {"overall": 100.4, "per_intent": {}}) == []


def test_fewshot_deterministic():
    a = export_fewshot(["YES", "NO"], 2)
    assert a == export_fewshot(["NO", "YES"], 2)
    assert len(a) == 4 and a[0].endswith("-> NO") and a[-1].endswith("-> YES")
    assert all(line.startswith('reply: "') for line in a)
    assert export_fewshot(["NO_SUCH"], 3) == []


def test_real_labels_against_real_baseline():
    labels = load_labels()
    assert len(labels) >= 100
    rep = ev.evaluate(labels)
    base = ev.load_baseline()
    assert base is not None
    assert ev.regressions(rep, base) == []
