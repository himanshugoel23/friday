"""The small trained intent classifier: determinism, threshold, gate, versioning, fallback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from friday.learning import cli as learn_cli
from friday.learning.classifier_data import (
    Example,
    bucket,
    build_training_set,
    data_hash,
    split_labels,
)
from friday.learning.classifier_train import (
    PRECISION_FLOOR,
    TrainConfig,
    apply_gate,
    evaluate_model,
    run_training,
    train_classifier,
    wilson_low,
)
from friday.learning.labels import load_labels
from friday.learning.synth import CORES, generate
from friday.playbooks import classifier as clf
from friday.playbooks.classifier import (
    SAFE_INTENTS,
    ClassifierDecision,
    IntentClassifier,
    Prediction,
    decide,
    featurize,
    load_active,
    normalise_text,
)
from friday.playbooks.engine import PlaybookPolicy
from friday.playbooks.intents import INTENTS
from tests.latency.test_speculative import UNSURE, CountingUnderstander, _commit, _waiting


# --------------------------------------------------------------------------- the data
def test_synthetic_data_is_deterministic_and_seeded():
    assert generate(7) == generate(7)
    assert generate(7) != generate(8)
    assert {i for _t, i in generate(7)} == set(CORES) <= INTENTS
    assert len({(t, i) for t, i in generate(7)}) == len(generate(7))  # no duplicates


def test_the_held_out_labels_are_never_trained_on():
    train, gold, held = build_training_set()
    assert held, "the evaluation set must not be empty"
    train_keys = {normalise_text(e.text) for e in train}
    for lb in held:
        assert normalise_text(lb.text) not in train_keys, lb.text
    labels = load_labels()
    tr, ho = split_labels(labels)
    assert len(tr) + len(ho) == len(labels) and not ({x.text for x in tr} & {x.text for x in ho})
    assert [bucket(x.text) for x in ho] == [bucket(x.text) for x in split_labels(labels)[1]]


def test_training_data_comes_from_the_repo_not_from_var(tmp_path, monkeypatch):
    var = tmp_path / "var" / "learning"
    var.mkdir(parents=True)
    (var / "utterances.jsonl").write_text(
        json.dumps({"text": "CANARY real vendor sentence", "intent": "YES"}) + "\n"
    )
    monkeypatch.chdir(tmp_path)
    train, _gold, _held = build_training_set()
    assert not any("canary" in e.text.lower() for e in train)
    sources = {e.source for e in train}
    assert sources == {"labels", "tests", "personas", "synth"}


def test_every_training_intent_is_a_real_intent_and_texts_are_unique():
    train, _g, _h = build_training_set()
    assert {e.intent for e in train} <= INTENTS
    keys = [normalise_text(e.text) for e in train]
    assert len(keys) == len(set(keys))


def test_data_hash_changes_with_the_data(tmp_path):
    src = Path(clf.LEARNING_DIR / "labels.yaml").read_text(encoding="utf-8")
    p1 = tmp_path / "a.yaml"
    p1.write_text(src, encoding="utf-8")
    train1, _g, held1 = build_training_set(p1)
    # a new labelled sentence that lands in the training share changes the hash
    n = 0
    while True:
        text = f"yeh ek naya test vaakya number {n}"
        if bucket(text) >= 2:
            break
        n += 1
    p2 = tmp_path / "b.yaml"
    p2.write_text(src + f'- {{text: "{text}", intent: "YES"}}\n', encoding="utf-8")
    train2, _g2, held2 = build_training_set(p2)
    assert data_hash(train1, held1) == data_hash(train1, held1)
    assert data_hash(train1, held1) != data_hash(train2, held2)


# --------------------------------------------------------------------------- the model
def test_features_are_stable_and_normalised():
    assert normalise_text("Haan JI, 400 rupaye!") == "haan ji <num> rupaye"
    assert normalise_text("हाँ जी।") == "हाँ जी"
    a, b = featurize("haan ji bataiye"), featurize("haan ji bataiye")
    assert a == b and abs(sum(v * v for v in a.values()) - 1.0) < 1e-9
    assert featurize("") == {} and featurize("...") == {}


def test_training_is_deterministic_and_the_file_round_trips():
    train, _g, _h = build_training_set()
    m1, m2 = train_classifier(train), train_classifier(train)
    assert m1.dumps() == m2.dumps()
    again = IntentClassifier.loads(m1.dumps())
    for text in ("haan ji", "nahi sir", "ek minute ruko", "400 rupaye lagega", "kuch bhi"):
        assert again.predict(text) == m1.predict(text)
    assert len(m1.dumps()) < 500_000  # a small JSON file
    other = train_classifier(train, TrainConfig(alpha=0.5))
    assert other.dumps() != m1.dumps()


def test_a_tiny_trained_model_predicts_with_confidence():
    ex = [Example(t, i, "synth") for t, i in generate(7) if i in ("YES", "NO", "HOLD_ON")]
    m = train_classifier(ex, TrainConfig(alpha=0.1, beta=1.0))
    assert m.predict("haan ji").intent == "YES"
    assert m.predict("nahi nahi").intent == "NO"
    p = m.predict("ek minute ruko zara")
    assert p.intent == "HOLD_ON" and 0 < p.confidence <= 1
    assert m.predict("").confidence == 0.0


# --------------------------------------------------------------------------- the threshold
class FixedModel:
    """Says the same thing every time; counts how often it was asked."""

    def __init__(self, intent: str, confidence: float) -> None:
        self.intent, self.confidence, self.asked = intent, confidence, 0

    def predict(self, _text: str) -> Prediction:
        self.asked += 1
        return Prediction(self.intent, self.confidence)


def test_threshold_behaviour():
    m: Any = FixedModel("YES", 0.93)
    assert decide("x", m, 0.9).used is True and decide("x", m, 0.9).reason == "hit"
    assert decide("x", m, 0.95) == ClassifierDecision("YES", 0.93, False, "below_threshold")
    assert decide("x", m, 0.93).used is True  # at the threshold is enough
    assert decide("x", None, 0.5).reason == "no_model"


def test_only_value_free_intents_are_ever_answered_by_the_classifier():
    for intent in ("GIVES_PRICE", "PRICE_RANGE", "GIVES_TIME", "SLOT_FREE", "OFFERS_SLOTS",
                   "GIVES_STYLIST", "GIVES_NUMBER", "NEEDS_ADVANCE", "NO_ADVANCE"):
        assert decide("x", FixedModel(intent, 1.0), 0.5) == ClassifierDecision(
            intent, 1.0, False, "not_safe_intent")
    for hard in ("STOP_CALLING", "ASKS_SECRET", "RUDE", "ARE_YOU_BOT", "UNCLEAR"):
        assert hard not in SAFE_INTENTS
    assert decide("x", FixedModel("YES", 1.0), 0.5, allowed={"NO"}).reason == "not_allowed_here"
    assert SAFE_INTENTS <= INTENTS


# --------------------------------------------------------------------------- the engine path
async def test_classifier_above_threshold_means_no_model_call():
    und = CountingUnderstander()
    fixed = FixedModel("YES", 0.97)
    pol = PlaybookPolicy(understander=und, llm_mode="auto", classifier=fixed,  # type: ignore[arg-type]
                         classifier_threshold=0.9)
    brief, run = await _waiting(pol)
    _commit(run, UNSURE)
    await pol.next_call_action(brief, run.transcript, [])
    assert und.calls == [] and fixed.asked == 1
    assert pol.stats["classifier_hit"] == 1 and run.state.llm_calls == 0
    assert run.state.intents[-1] == "YES"


async def test_below_threshold_falls_back_to_the_model_path():
    und = CountingUnderstander(intent="NO")
    pol = PlaybookPolicy(understander=und, llm_mode="auto", classifier=FixedModel("YES", 0.6),  # type: ignore[arg-type]
                         classifier_threshold=0.9)
    brief, run = await _waiting(pol)
    _commit(run, UNSURE)
    await pol.next_call_action(brief, run.transcript, [])
    assert und.calls == [UNSURE] and pol.stats["classifier_miss"] == 1
    assert run.state.intents[-1] == "NO"  # the model's answer, not the classifier's


async def test_an_intent_the_step_does_not_allow_falls_back_to_the_model():
    und = CountingUnderstander()
    pol = PlaybookPolicy(understander=und, llm_mode="auto",
                         classifier=FixedModel("OUT_OF_STOCK", 0.99),  # type: ignore[arg-type]
                         classifier_threshold=0.9)
    brief, run = await _waiting(pol)
    assert "OUT_OF_STOCK" not in pol._allowed(pol.playbook(brief), run.state.step)
    _commit(run, UNSURE)
    await pol.next_call_action(brief, run.transcript, [])
    assert und.calls == [UNSURE]


async def test_confident_rules_win_and_the_classifier_is_not_even_asked():
    und = CountingUnderstander()
    fixed = FixedModel("NO", 0.99)
    pol = PlaybookPolicy(understander=und, llm_mode="auto", classifier=fixed)  # type: ignore[arg-type]
    brief, run = await _waiting(pol)
    _commit(run, "haan ji bataiye")
    await pol.next_call_action(brief, run.transcript, [])
    assert fixed.asked == 0 and und.calls == []


async def test_a_stop_request_never_reaches_the_classifier():
    fixed = FixedModel("YES", 0.99)
    pol = PlaybookPolicy(understander=CountingUnderstander(), llm_mode="auto",
                         classifier=fixed)  # type: ignore[arg-type]
    brief, run = await _waiting(pol)
    _commit(run, "dobara call mat karna")
    await pol.next_call_action(brief, run.transcript, [])
    assert fixed.asked == 0 and run.state.intents[-1] == "STOP_CALLING"


async def test_without_a_classifier_nothing_changes():
    und = CountingUnderstander()
    pol = PlaybookPolicy(understander=und, llm_mode="auto")
    assert pol.classifier is None
    brief, run = await _waiting(pol)
    _commit(run, UNSURE)
    await pol.next_call_action(brief, run.transcript, [])
    assert und.calls == [UNSURE] and not pol.stats


# --------------------------------------------------------------------------- the gate
def _metrics(**kw: Any) -> dict[str, Any]:
    base = {"n": 50, "threshold": 0.9, "fires": 22, "precision": 1.0,
            "combined_accuracy": 80.0, "rules_accuracy": 74.0}
    base.update(kw)
    return base


def test_gate_passes_a_good_model():
    g = apply_gate(_metrics())
    assert g.passed and not g.reasons


@pytest.mark.parametrize(
    ("kw", "name"),
    [
        ({"precision": 0.97}, "precision"),
        ({"precision": PRECISION_FLOOR - 0.001}, "precision"),
        ({"fires": 3}, "enough_fires"),
        ({"n": 10}, "enough_eval"),
        ({"combined_accuracy": 70.0}, "beats_rules"),
    ],
)
def test_gate_refuses(kw, name):
    g = apply_gate(_metrics(**kw))
    assert not g.passed
    assert name in [c["name"] for c in g.checks if not c["ok"]]


def test_gate_refuses_a_model_that_loses_to_the_current_one():
    cur = _metrics(combined_accuracy=82.0)
    assert not apply_gate(_metrics(combined_accuracy=80.0), cur).passed
    assert not apply_gate(_metrics(precision=0.985), _metrics()).passed
    assert apply_gate(_metrics(combined_accuracy=82.0), cur).passed


def test_wilson_interval_is_honest_about_small_samples():
    assert wilson_low(22, 22) < 0.9  # 22 of 22 does not prove 98%
    assert wilson_low(0, 0) == 0.0
    assert wilson_low(990, 1000) > 0.98


def test_evaluate_model_reports_per_intent_confusions_and_the_baseline():
    train, _g, held = build_training_set()
    m = train_classifier(train)
    r = evaluate_model(m, held, 0.9)
    assert r["n"] == len(held) and set(r["per_intent"]) == {lb.intent for lb in held}
    assert {"classifier_accuracy", "rules_accuracy", "combined_accuracy", "precision",
            "confusion_pairs", "misses"} <= set(r)
    assert all({"expected", "got", "count"} == set(c) for c in r["confusion_pairs"])


# --------------------------------------------------------------------------- pipeline + versioning
@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    d = tmp_path_factory.mktemp("clf")
    mp, vp = d / "m.json", d / "m.version.json"
    res = run_training(model_path=mp, version_path=vp)
    return res, mp, vp


def test_pipeline_writes_model_and_version_file_when_the_gate_passes(trained):
    res, mp, vp = trained
    assert res.gate.passed and res.written
    ver = json.loads(vp.read_text())
    import hashlib

    assert ver["model_sha256"] == hashlib.sha256(mp.read_bytes()).hexdigest()
    _t, _g, held = build_training_set()
    train, _g2, _h2 = build_training_set()
    assert ver["data_hash"] == data_hash(train, held)
    assert ver["eval_count"] == len(held) and ver["train_count"] == len(train)
    assert ver["gate"]["passed"] is True and ver["metrics"]["precision"] >= PRECISION_FLOOR
    assert 0.9 <= ver["threshold"] <= 1.0 and ver["threshold_source"] == "cross_validation"
    assert "misses" not in ver["metrics"] and "real call data" in ver["data_note"]


def test_pipeline_is_reproducible(trained, tmp_path):
    res, mp, vp = trained
    again = run_training(model_path=tmp_path / "x.json", version_path=tmp_path / "x.v.json")
    assert (tmp_path / "x.json").read_bytes() == mp.read_bytes()
    assert again.version["data_hash"] == res.version["data_hash"]
    assert again.version["model_sha256"] == res.version["model_sha256"]
    assert again.version["metrics"] == res.version["metrics"]


def test_a_worse_model_is_refused_and_the_files_are_untouched(trained, tmp_path):
    res, mp, vp = trained
    m2, v2 = tmp_path / "m.json", tmp_path / "m.version.json"
    m2.write_bytes(mp.read_bytes())
    v2.write_bytes(vp.read_bytes())
    before = (m2.read_bytes(), v2.read_bytes())
    empty = tmp_path / "empty"
    empty.mkdir()
    bad = run_training(model_path=m2, version_path=v2, synth=False, test_dir=empty,
                       playbook_dir=empty)
    assert not bad.gate.passed and not bad.written
    assert (m2.read_bytes(), v2.read_bytes()) == before
    assert bad.gate.reasons


def test_an_explicit_threshold_is_recorded_as_such(tmp_path):
    r = run_training(model_path=tmp_path / "m.json", version_path=tmp_path / "v.json",
                     threshold=0.95, write=False)
    assert r.version["threshold"] == 0.95 and r.version["threshold_source"] == "cli"
    assert not (tmp_path / "m.json").exists()  # write=False writes nothing


def test_load_active_needs_a_passed_gate_and_a_matching_sha(trained, tmp_path):
    _res, mp, vp = trained
    assert isinstance(load_active(mp, vp), IntentClassifier)
    ver = json.loads(vp.read_text())
    bad = tmp_path / "v1.json"
    bad.write_text(json.dumps({**ver, "gate": {"passed": False, "checks": []}}))
    assert load_active(mp, bad) is None
    bad2 = tmp_path / "v2.json"
    bad2.write_text(json.dumps({**ver, "model_sha256": "0" * 64}))
    assert load_active(mp, bad2) is None
    assert load_active(tmp_path / "nope.json", vp) is None


# --------------------------------------------------------------------------- the repo's own model
def test_the_committed_model_is_gate_passed_current_and_honest():
    ver = clf.load_version()
    assert ver is not None, "run: friday learn train-classifier"
    assert ver["gate"]["passed"] is True
    assert ver["model_sha256"] == clf.file_sha(clf.MODEL_PATH)
    assert ver["metrics"]["precision"] >= PRECISION_FLOOR
    assert ver["metrics"]["combined_accuracy"] >= ver["metrics"]["rules_accuracy"]
    model = load_active()
    assert model is not None
    train, _g, held = build_training_set()
    assert ver["data_hash"] == data_hash(train, held), "data changed: retrain the classifier"
    m = evaluate_model(model, held, ver["threshold"])
    assert m["precision"] >= PRECISION_FLOOR and m["combined_accuracy"] >= m["rules_accuracy"]


def test_cli_eval_and_dry_run_train(capsys):
    rc = learn_cli.run(argparse.Namespace(learn_cmd="eval-classifier", model=None, threshold=None,
                                          all_labels=False))
    out = capsys.readouterr().out
    assert rc == 0 and "per intent" in out and "confusion pairs" in out and "gate ok" in out
    rc = learn_cli.run(argparse.Namespace(learn_cmd="train-classifier", dry_run=True, seed=7,
                                          threshold=None, model=None))
    out = capsys.readouterr().out
    assert rc == 0 and "dry run" in out and "data hash" in out


def test_cli_eval_without_a_model_says_so(tmp_path, capsys):
    rc = learn_cli.run(argparse.Namespace(learn_cmd="eval-classifier",
                                          model=str(tmp_path / "none.json"), threshold=None,
                                          all_labels=False))
    assert rc == 2 and "no usable model" in capsys.readouterr().out
