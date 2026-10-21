# ruff: noqa: E501
"""Train, evaluate and gate the semantic end-of-turn model (pure Python, deterministic, offline).

Pipeline behind ``friday learn train-eot``:

1. read the hand-written list (``data/eot_examples.txt``): ``train`` rows may be trained on, ``test``
   rows are the HELD-OUT set (never trained on, never used to choose anything); add the deterministic
   synthetic rows (``eot_synth``) minus anything that equals a held-out sentence,
2. choose smoothing, sharpness and the confidence threshold by 5-fold cross-validation on the
   hand-written TRAIN rows (synthetic rows are always in the training folds),
3. train the final model, score it on the held-out rows against the rules-only baseline,
4. apply the REGRESSION GATE and write the model + version file only if it passes.

Gate: the model (rules + model) must beat the rules-only baseline on the held-out set AND the false-cut
rate (caller unfinished but judged complete, so an early commit would cut them off) must be at most 2%
at the chosen threshold. A refused model is never written.

Metrics (``evaluate``): accuracy (an "unsure" counts as wrong: the system said nothing useful), accuracy
on the decided ones and the coverage, precision / recall / F1 per class, the false-cut rate (share of the
unfinished utterances judged complete), the false-extend rate (finished utterances judged unfinished: a
pointless extra wait), and the mean added delay in milliseconds.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.learning import eot_synth
from friday.voice.eot import (
    CLASSES,
    MODEL_PATH,
    VERSION_PATH,
    EotModel,
    SemanticEot,
    Verdict,
    featurize,
    load_version,
    tokens_of,
)

DATA_PATH = Path(__file__).resolve().parent / "data" / "eot_examples.txt"
FALSE_CUT_CEILING = 0.02
CV_FALSE_CUT_TARGET = 0.015  # the threshold is picked on CV with a margin under the ceiling
MIN_TEST = 100
MIN_TEST_INCOMPLETE = 30
THRESHOLD_GRID = (0.8, 0.85, 0.9, 0.93, 0.95, 0.97, 0.98, 0.99)
ALPHA_GRID = (0.1, 0.3, 1.0)
BETA_GRID = (0.1, 0.2, 0.4, 0.8, 1.6)
CODE_VERSION = 1
SYNTH_WEIGHT = 1.0
GOLD_WEIGHT = 3.0
# delays used by the report (documented assumptions, see docs/LATENCY.md)
EARLY_COMMIT_SAVES_MS = 310  # a short answer: 650 ms short wait vs the ~340 ms early point
DEFAULT_EXTEND_MS = 700


@dataclass(frozen=True)
class Example:
    text: str
    label: str  # "complete" | "incomplete"
    answer_type: str = ""
    weight: float = 1.0
    source: str = "gold"


@dataclass(frozen=True)
class TrainConfig:
    seed: int = 7
    alpha: float = 0.3
    beta: float = 0.4
    min_mass: float = 0.05


def _key(text: str) -> str:
    return " ".join(tokens_of(text))


def load_gold(path: Path | None = None) -> tuple[list[Example], list[Example]]:
    """(train, test) from the hand-written file. Malformed lines raise: the data is checked in."""
    train: list[Example] = []
    test: list[Example] = []
    for n, line in enumerate((path or DATA_PATH).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("|", 3)
        if len(parts) != 4 or parts[0] not in ("train", "test") or parts[1] not in CLASSES:
            raise ValueError(f"{path or DATA_PATH}:{n}: bad line {line!r}")
        ex = Example(parts[3].strip(), parts[1], parts[2].strip(), GOLD_WEIGHT, "gold")
        (train if parts[0] == "train" else test).append(ex)
    return train, test


def build_training_set(
    seed: int = 7, gold_train: list[Example] | None = None, gold_test: list[Example] | None = None
) -> tuple[list[Example], list[Example], list[Example]]:
    """(all training examples, gold train only, held-out test). Anything equal to a held-out
    sentence is dropped from the training data."""
    g_train, g_test = load_gold()
    g_train = gold_train if gold_train is not None else g_train
    g_test = gold_test if gold_test is not None else g_test
    held = {_key(e.text) for e in g_test}
    synth = [
        Example(t, lab, at, SYNTH_WEIGHT, "synthetic")
        for t, lab, at in eot_synth.generate(seed)
        if _key(t) not in held
    ]
    gold = [e for e in g_train if _key(e.text) not in held]
    return gold + synth, gold, g_test


def data_hash(examples: list[Example], test: list[Example]) -> str:
    h = hashlib.sha256()
    for e in sorted(examples, key=lambda e: (e.text, e.label, e.answer_type, e.source)):
        h.update(f"{e.source}|{e.label}|{e.answer_type}|{e.weight}|{e.text}\n".encode())
    h.update(b"--test--")
    for e in sorted(test, key=lambda e: e.text):
        h.update(f"{e.label}|{e.answer_type}|{e.text}\n".encode())
    return h.hexdigest()


# --------------------------------------------------------------------------- training
def _counts(examples: list[Example], min_mass: float) -> dict[int, tuple[tuple[int, float], ...]]:
    acc: dict[int, dict[int, float]] = {}
    for e in examples:
        c = CLASSES.index(e.label)
        for f, v in featurize(e.text, e.answer_type).items():
            row = acc.setdefault(f, {})
            row[c] = row.get(c, 0.0) + v * e.weight
    out = {f: tuple(sorted((c, m) for c, m in row.items() if m >= min_mass)) for f, row in sorted(acc.items())}
    return {f: cw for f, cw in out.items() if cw}


def train_model(examples: list[Example], cfg: TrainConfig | None = None) -> EotModel:
    cfg = cfg or TrainConfig()
    # round-trip through the file format: the model that is scored is exactly the model that ships
    return EotModel.loads(EotModel(_counts(examples, cfg.min_mass), cfg.alpha, cfg.beta).dumps())


# --------------------------------------------------------------------------- evaluation
def _outcome(det: SemanticEot, e: Example) -> Verdict:
    return det.assess(e.text, e.answer_type).verdict


def evaluate(
    det: SemanticEot, items: list[Example], *, extend_ms: int = DEFAULT_EXTEND_MS,
    save_ms: int = EARLY_COMMIT_SAVES_MS,
) -> dict[str, Any]:
    n = len(items)
    pred = [(_outcome(det, e), e) for e in items]
    gold_c = [e for e in items if e.label == "complete"]
    gold_i = [e for e in items if e.label == "incomplete"]
    ok = sum(1 for v, e in pred if v.value == e.label)
    decided = [(v, e) for v, e in pred if v is not Verdict.UNSURE]
    dec_ok = sum(1 for v, e in decided if v.value == e.label)
    per: dict[str, dict[str, float]] = {}
    for cls in CLASSES:
        tp = sum(1 for v, e in pred if v.value == cls and e.label == cls)
        said = sum(1 for v, _e in pred if v.value == cls)
        gold = sum(1 for _v, e in pred if e.label == cls)
        p = tp / said if said else 0.0
        r = tp / gold if gold else 0.0
        per[cls] = {"precision": round(p, 4), "recall": round(r, 4),
                    "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
                    "said": said, "gold": gold, "correct": tp}
    false_cut = [e for v, e in pred if v is Verdict.COMPLETE and e.label == "incomplete"]
    false_ext = [e for v, e in pred if v is Verdict.INCOMPLETE and e.label == "complete"]
    good_ext = [e for v, e in pred if v is Verdict.INCOMPLETE and e.label == "incomplete"]
    good_commit = [e for v, e in pred if v is Verdict.COMPLETE and e.label == "complete"]
    return {
        "n": n, "n_complete": len(gold_c), "n_incomplete": len(gold_i),
        "accuracy": round(ok / n, 4) if n else 0.0,
        "decided": len(decided), "coverage": round(len(decided) / n, 4) if n else 0.0,
        "decided_accuracy": round(dec_ok / len(decided), 4) if decided else 0.0,
        "per_class": per,
        "false_cut_rate": round(len(false_cut) / len(gold_i), 4) if gold_i else 0.0,
        "false_cut_rate_all_turns": round(len(false_cut) / n, 4) if n else 0.0,
        "false_cut_count": len(false_cut),
        "false_extend_rate": round(len(false_ext) / len(gold_c), 4) if gold_c else 0.0,
        "false_extend_count": len(false_ext),
        "extended_correctly": len(good_ext),
        "committed_early_correctly": len(good_commit),
        # MEAN ADDED DELAY (ms, averaged over the finished turns): the pointless extra wait when a
        # finished answer is judged unfinished. This is the real cost and it does not depend on the STT.
        "added_delay_ms_on_finished": round(len(false_ext) * extend_ms / len(gold_c), 1) if gold_c else 0.0,
        # the most an early commit could save, ONLY if the text is ready before the wait ends (a streaming
        # partial at ~350 ms; with REST speech-to-text the text arrives at ~840 ms, after the 650 ms wait,
        # and the saving is ~0: see friday/latency/eot_sim.py)
        "potential_saving_ms_on_finished": round(len(good_commit) * save_ms / len(gold_c), 1) if gold_c else 0.0,
        "extra_wait_ms_on_unfinished": round(len(good_ext) * extend_ms / len(gold_i), 1) if gold_i else 0.0,
        "mistakes": [
            {"text": e.text, "gold": e.label, "said": v.value, "type": e.answer_type}
            for v, e in pred if v is not Verdict.UNSURE and v.value != e.label
        ],
        "unsure": [{"text": e.text, "gold": e.label, "type": e.answer_type}
                   for v, e in pred if v is Verdict.UNSURE],
    }


def format_eval(m: dict[str, Any], title: str = "") -> str:
    lines = [title] if title else []
    lines.append(f"  items {m['n']} ({m['n_complete']} finished, {m['n_incomplete']} unfinished)")
    lines.append(f"  accuracy (unsure = wrong) {m['accuracy']:.1%}   decided {m['decided']} "
                 f"(coverage {m['coverage']:.1%}), accuracy on decided {m['decided_accuracy']:.1%}")
    for cls in CLASSES:
        c = m["per_class"][cls]
        lines.append(f"  {cls:<10} precision {c['precision']:.1%}  recall {c['recall']:.1%}  f1 {c['f1']:.3f}"
                     f"   (said {c['said']}, gold {c['gold']}, right {c['correct']})")
    lines.append(f"  FALSE-CUT rate {m['false_cut_rate']:.1%} ({m['false_cut_count']} of {m['n_incomplete']} unfinished judged finished; "
                 f"{m['false_cut_rate_all_turns']:.1%} of all turns)")
    lines.append(f"  false-extend rate {m['false_extend_rate']:.1%} ({m['false_extend_count']} of {m['n_complete']} finished judged unfinished)")
    lines.append(f"  mean added delay on finished turns +{m['added_delay_ms_on_finished']:.0f} ms (false extends); "
                 f"mean extra wait on unfinished turns +{m['extra_wait_ms_on_unfinished']:.0f} ms (intended); "
                 f"potential early-commit saving -{m['potential_saving_ms_on_finished']:.0f} ms (only if the text is ready in time)")
    return "\n".join(lines)


# --------------------------------------------------------------------------- gate
@dataclass
class Gate:
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)


def apply_gate(model_m: dict[str, Any], base_m: dict[str, Any], threshold: float) -> Gate:
    checks = []

    def chk(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    chk("held-out size", model_m["n"] >= MIN_TEST and model_m["n_incomplete"] >= MIN_TEST_INCOMPLETE,
        f"{model_m['n']} sentences ({model_m['n_incomplete']} unfinished); need >= {MIN_TEST} and >= {MIN_TEST_INCOMPLETE}")
    chk("beats the rules-only baseline", model_m["accuracy"] > base_m["accuracy"],
        f"accuracy {model_m['accuracy']:.1%} vs rules-only {base_m['accuracy']:.1%} (unsure counts as wrong)")
    chk("false-cut rate <= 2%", model_m["false_cut_rate"] <= FALSE_CUT_CEILING,
        f"{model_m['false_cut_rate']:.1%} ({model_m['false_cut_count']} of {model_m['n_incomplete']}) at threshold {threshold}")
    chk("no more false cuts than the baseline", model_m["false_cut_count"] <= base_m["false_cut_count"] + 1,
        f"{model_m['false_cut_count']} vs rules-only {base_m['false_cut_count']} (+1 allowed)")
    return Gate(all(c["ok"] for c in checks), checks)


# --------------------------------------------------------------------------- cross-validation
def _folds(gold: list[Example], k: int = 5) -> list[list[Example]]:
    out: list[list[Example]] = [[] for _ in range(k)]
    for e in gold:
        out[int(hashlib.sha256(_key(e.text).encode()).hexdigest(), 16) % k].append(e)
    return out


def cross_validate(
    train: list[Example], gold: list[Example], min_mass: float = 0.05
) -> dict[str, Any]:
    """Pick (alpha, beta) by log-loss and the threshold by the smallest false-cut / best accuracy,
    scoring only the hand-written TRAIN rows of the held-out fold. The test set is never used."""
    folds = _folds(gold)
    synth = [e for e in train if e.source == "synthetic"]
    table: list[dict[str, Any]] = []
    fold_counts = []
    for i, held in enumerate(folds):
        held_keys = {_key(e.text) for e in held}
        rest = [e for j, f in enumerate(folds) if j != i for e in f]
        tr = rest + [e for e in synth if _key(e.text) not in held_keys]
        fold_counts.append(_counts(tr, min_mass))
    for alpha in ALPHA_GRID:
        for beta in BETA_GRID:
            probs: list[tuple[Example, float]] = []
            for held, counts in zip(folds, fold_counts, strict=True):
                model = EotModel.loads(EotModel(counts, alpha, beta).dumps())
                probs += [(e, model.p_complete(e.text, e.answer_type)) for e in held]
            ll = -sum(math.log(max(1e-6, p if e.label == "complete" else 1 - p)) for e, p in probs) / len(probs)
            table.append({"alpha": alpha, "beta": beta, "logloss": round(ll, 4)})
    best = min(table, key=lambda r: r["logloss"])
    # threshold: re-run the full detector (rules + model) per fold at the chosen alpha / beta
    models = [EotModel.loads(EotModel(c, best["alpha"], best["beta"]).dumps()) for c in fold_counts]
    thr_rows = []
    for thr in THRESHOLD_GRID:
        items_pred: list[tuple[Example, Verdict]] = []
        for held, model in zip(folds, models, strict=True):
            det = SemanticEot(model, thr)
            items_pred += [(e, _outcome(det, e)) for e in held]
        inc = [e for e, _v in items_pred if e.label == "incomplete"]
        cuts = sum(1 for e, v in items_pred if e.label == "incomplete" and v is Verdict.COMPLETE)
        ok = sum(1 for e, v in items_pred if v.value == e.label)
        thr_rows.append({"threshold": thr, "false_cut_rate": round(cuts / len(inc), 4) if inc else 0.0,
                         "accuracy": round(ok / len(items_pred), 4), "n": len(items_pred)})
    eligible = [r for r in thr_rows if r["false_cut_rate"] <= CV_FALSE_CUT_TARGET]
    chosen = max(eligible, key=lambda r: (r["accuracy"], -r["threshold"])) if eligible else thr_rows[-1]
    return {"grid": table, "best": best, "thresholds": thr_rows, "chosen_threshold": chosen["threshold"],
            "threshold_met_target": bool(eligible), "folds": len(folds), "n": sum(len(f) for f in folds)}


# --------------------------------------------------------------------------- pipeline
@dataclass
class TrainResult:
    model: EotModel
    version: dict[str, Any]
    metrics: dict[str, Any]
    baseline: dict[str, Any]
    gate: Gate
    cv: dict[str, Any]
    written: bool


def run_training(
    *, cfg: TrainConfig | None = None, threshold: float | None = None,
    model_path: Path | None = None, version_path: Path | None = None, write: bool = True,
) -> TrainResult:
    cfg = cfg or TrainConfig()
    model_path = model_path or MODEL_PATH
    version_path = version_path or VERSION_PATH
    train, gold, held = build_training_set(cfg.seed)
    cv = cross_validate(train, gold, cfg.min_mass)
    alpha, beta = cv["best"]["alpha"], cv["best"]["beta"]
    thr = threshold if threshold is not None else cv["chosen_threshold"]
    model = train_model(train, TrainConfig(cfg.seed, alpha, beta, cfg.min_mass))
    metrics = evaluate(SemanticEot(model, thr), held)
    baseline = evaluate(SemanticEot(None, thr, rules_only=True), held)
    gate = apply_gate(metrics, baseline, thr)
    by_source: dict[str, int] = {}
    for e in train:
        by_source[e.source] = by_source.get(e.source, 0) + 1
    version = {
        "code_version": CODE_VERSION,
        "data_hash": data_hash(train, held),
        "model_sha256": hashlib.sha256(model.dumps().encode()).hexdigest(),
        "train_count": len(train), "train_by_source": by_source, "held_out_count": len(held),
        "alpha": alpha, "beta": beta, "threshold": thr,
        "threshold_source": "given" if threshold is not None else "cross-validation (false-cut <= 1.5%)",
        "cross_validation": {"best": cv["best"], "thresholds": cv["thresholds"], "folds": cv["folds"]},
        "held_out": {k: v for k, v in metrics.items() if k not in ("mistakes", "unsure")},
        "rules_only_baseline": {k: v for k, v in baseline.items() if k not in ("mistakes", "unsure")},
        "gate": {"passed": gate.passed, "checks": gate.checks},
        "trained_on_held_out": False,
    }
    written = False
    if write and gate.passed:
        old = load_version(version_path)
        if old and (old.get("gate") or {}).get("passed"):
            checks = gate.checks + [{
                "name": "not worse than the model in the repo",
                "ok": metrics["accuracy"] >= (old.get("held_out") or {}).get("accuracy", 0.0),
                "detail": f"{metrics['accuracy']:.1%} vs {(old.get('held_out') or {}).get('accuracy', 0.0):.1%} (same held-out set)",
            }]
            gate = Gate(all(c["ok"] for c in checks), checks)
            version["gate"] = {"passed": gate.passed, "checks": gate.checks}
        if gate.passed:
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_text(model.dumps(), encoding="utf-8")
            version_path.write_text(json.dumps(version, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written = True
    return TrainResult(model, version, metrics, baseline, gate, cv, written)
