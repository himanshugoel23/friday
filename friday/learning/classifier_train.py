# ruff: noqa: E501
"""Train, evaluate and gate the intent classifier (pure Python, deterministic, offline).

``train_classifier`` counts hashed word / character n-gram features per intent (multinomial naive
Bayes: no randomness, so the same data always gives the same bytes). ``run_training`` is the
whole pipeline behind ``friday learn train-classifier``:

1. build the training set from repo data (``classifier_data``) and hold out the evaluation labels,
2. choose the smoothing, the confidence sharpness and the confidence threshold by 5-fold
   cross-validation on the gold training examples (never on the held-out set),
3. train the final model, score it on the held-out set against the current rules baseline,
4. apply the REGRESSION GATE and write the model + version file only if it passes.

The gate refuses a model whose precision at the chosen threshold is below 98%, that fires too
rarely to prove anything, that loses to the rules on the held-out set, or that loses to the model
already in the repo on the same set. A refused model is never written.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.learning.classifier_data import Example, build_training_set, data_hash
from friday.learning.labels import Label
from friday.playbooks.classifier import (
    MODEL_PATH,
    SAFE_INTENTS,
    VERSION_PATH,
    IntentClassifier,
    decide,
    featurize,
    load_version,
)
from friday.playbooks.intents import INTENTS
from friday.playbooks.understand import heuristic

PRECISION_FLOOR = 0.98
MIN_EVAL = 30
MIN_FIRES = 10
THRESHOLD_GRID = (0.9, 0.93, 0.95, 0.97, 0.98, 0.99, 0.995)
CODE_VERSION = 1


@dataclass(frozen=True)
class TrainConfig:
    seed: int = 7  # seeds the synthetic data; naive Bayes itself has no randomness
    alpha: float = 0.2  # smoothing
    beta: float = 4.0  # confidence sharpness: softmax(beta * log-likelihood)
    min_mass: float = 0.1  # a (feature, intent) pair with less total weight is not stored


ALPHA_GRID = (0.05, 0.1, 0.2, 0.5)
BETA_GRID = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)


# --------------------------------------------------------------------------- training
def train_classifier(examples: list[Example], cfg: TrainConfig | None = None) -> IntentClassifier:
    cfg = cfg or TrainConfig()
    classes = sorted({e.intent for e in examples})
    index = {c: i for i, c in enumerate(classes)}
    acc: dict[int, dict[int, float]] = {}
    for e in examples:
        c = index[e.intent]
        for f, v in featurize(e.text).items():
            row = acc.setdefault(f, {})
            row[c] = row.get(c, 0.0) + v * e.weight
    counts = {
        f: tuple(sorted((c, m) for c, m in row.items() if m >= cfg.min_mass))
        for f, row in sorted(acc.items())
    }
    counts = {f: cw for f, cw in counts.items() if cw}
    # round-trip through the file format: the model that is scored is exactly the model that ships
    return IntentClassifier.loads(IntentClassifier(classes, counts, cfg.alpha, cfg.beta).dumps())


# --------------------------------------------------------------------------- evaluation
def _rules(text: str) -> tuple[str, bool]:
    u = heuristic(text, known={"extended": True})
    return u.intent, u.confident


def wilson_low(ok: int, n: int, z: float = 1.96) -> float:
    """Lower end of the 95% Wilson interval for a proportion: how low the true precision could be
    given only ``n`` held-out answers (a small test set cannot prove 98%)."""
    if n == 0:
        return 0.0
    p = ok / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((centre - half) / d, 4)


def evaluate_model(
    model: IntentClassifier, held: list[Label], threshold: float
) -> dict[str, Any]:
    """Everything the gate and ``eval-classifier`` report, on the held-out labelled sentences."""
    per: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "clf": 0, "rules": 0, "combined": 0})
    confusion: Counter[tuple[str, str]] = Counter()
    fires = fires_ok = eng_fires = eng_ok = eng_rules_ok = 0
    clf_ok = rules_ok = comb_ok = 0
    misses: list[dict[str, Any]] = []
    for lb in held:
        p = model.predict(lb.text)
        d = decide(lb.text, model, threshold)
        r_intent, r_conf = _rules(lb.text)
        # what the live path would answer: rules if confident, else the classifier if it fires,
        # else the existing model path (offline: the fake model IS the rules)
        if r_conf:
            comb = r_intent
        elif d.used:
            comb = d.intent
        else:
            comb = r_intent
        row = per[lb.intent]
        row["n"] += 1
        row["clf"] += p.intent == lb.intent
        row["rules"] += r_intent == lb.intent
        row["combined"] += comb == lb.intent
        clf_ok += p.intent == lb.intent
        rules_ok += r_intent == lb.intent
        comb_ok += comb == lb.intent
        if p.intent != lb.intent:
            confusion[(lb.intent, p.intent)] += 1
            misses.append({"text": lb.text, "expected": lb.intent, "got": p.intent,
                           "confidence": p.confidence})
        if d.used:
            fires += 1
            fires_ok += d.intent == lb.intent
            if not r_conf:
                eng_fires += 1
                eng_ok += d.intent == lb.intent
                eng_rules_ok += r_intent == lb.intent
    n = len(held)
    pct = lambda a, b: round(100.0 * a / b, 2) if b else 0.0  # noqa: E731
    return {
        "n": n,
        "threshold": threshold,
        "classifier_accuracy": pct(clf_ok, n),
        "rules_accuracy": pct(rules_ok, n),
        "combined_accuracy": pct(comb_ok, n),
        "fires": fires,
        "fires_correct": fires_ok,
        "coverage": pct(fires, n),
        "precision": round(fires_ok / fires, 4) if fires else 0.0,
        "precision_ci95_low": wilson_low(fires_ok, fires),
        "engine_fires": eng_fires,
        "engine_fires_correct": eng_ok,
        "engine_fires_rules_correct": eng_rules_ok,
        "per_intent": {
            k: {
                "n": v["n"],
                "classifier": pct(v["clf"], v["n"]),
                "rules": pct(v["rules"], v["n"]),
                "combined": pct(v["combined"], v["n"]),
            }
            for k, v in sorted(per.items())
        },
        "confusion_pairs": [
            {"expected": a, "got": b, "count": c}
            for (a, b), c in sorted(confusion.items(), key=lambda kv: (-kv[1], kv[0]))
        ][:15],
        "misses": misses,
    }


def format_eval(m: dict[str, Any]) -> str:
    lines = [
        f"held-out sentences: {m['n']}   threshold: {m['threshold']}",
        f"classifier alone (argmax):        {m['classifier_accuracy']}%",
        f"rules baseline (offline model=rules): {m['rules_accuracy']}%",
        f"live path (rules, then classifier, then model): {m['combined_accuracy']}%",
        f"classifier answers on its own: {m['fires']} of {m['n']} ({m['coverage']}%), "
        f"correct {m['fires_correct']}, precision {m['precision'] * 100:.1f}% "
        f"(95% interval lower bound {m['precision_ci95_low'] * 100:.1f}%: small test set)",
        f"  of those where the rules were NOT confident: {m['engine_fires']} "
        f"(classifier right {m['engine_fires_correct']}, rules right {m['engine_fires_rules_correct']})",
        "per intent (classifier / rules / live path, n):",
    ]
    for k, v in m["per_intent"].items():
        lines.append(f"  {k:<20} {v['classifier']:6.1f} {v['rules']:6.1f} {v['combined']:6.1f}   n={v['n']}")
    if m["confusion_pairs"]:
        lines.append("confusion pairs (expected -> classifier got):")
        lines += [f"  {c['count']}x {c['expected']} -> {c['got']}" for c in m["confusion_pairs"]]
    return "\n".join(lines)


# --------------------------------------------------------------------------- threshold by CV
def cross_validate(
    train: list[Example], gold: list[Example], cfg: TrainConfig, folds: int = 5
) -> tuple[TrainConfig, float, dict[str, Any]]:
    """(config with the best alpha / beta, threshold, report). Out-of-fold predictions on the GOLD
    examples only; synthetic / persona examples are always in the training part of every fold.
    alpha / beta: lowest mean log-loss. Threshold: the lowest grid value >= 0.9 whose precision
    (over answers in ``SAFE_INTENTS``) is >= 98%, else the highest grid value."""
    gold_keys = {(e.text, e.intent) for e in gold}
    rest = [e for e in train if (e.text, e.intent) not in gold_keys]
    gold_sorted = sorted(gold, key=lambda e: hashlib.sha1(e.text.encode()).hexdigest())
    models: list[tuple[IntentClassifier, list[Example]]] = []
    for f in range(folds):
        test = gold_sorted[f::folds]
        keep = [e for i, e in enumerate(gold_sorted) if i % folds != f]
        models.append((train_classifier(rest + keep, cfg), test))
    best: tuple[float, float, float] | None = None
    for alpha in ALPHA_GRID:
        for beta in BETA_GRID:
            loss, n = 0.0, 0
            for m, test in models:
                mm = m.with_params(alpha, beta)
                for e in test:
                    p = mm.probabilities(e.text)
                    j = mm.classes.index(e.intent) if e.intent in mm.classes else -1
                    loss += -math.log(max(p[j], 1e-9)) if j >= 0 else 20.0
                    n += 1
            loss /= max(n, 1)
            if best is None or loss < best[0] - 1e-12:
                best = (loss, alpha, beta)
    assert best is not None
    cfg2 = TrainConfig(cfg.seed, best[1], best[2], cfg.min_mass)
    oof: list[tuple[str, float, str]] = []
    for m, test in models:
        mm = m.with_params(best[1], best[2])
        for e in test:
            p = mm.predict(e.text)
            oof.append((e.intent, p.confidence, p.intent))
    table: list[dict[str, Any]] = []
    chosen, found = THRESHOLD_GRID[-1], False
    for t in THRESHOLD_GRID:
        fired = [(y, p) for y, c, p in oof if c >= t and p in SAFE_INTENTS]
        ok = sum(1 for y, p in fired if y == p)
        prec = ok / len(fired) if fired else 0.0
        table.append({"threshold": t, "fires": len(fired), "precision": round(prec, 4)})
        if not found and t >= 0.9 and len(fired) >= 5 and prec >= PRECISION_FLOOR:
            chosen, found = t, True
    return cfg2, chosen, {
        "folds": folds, "gold_examples": len(oof), "alpha": best[1], "beta": best[2],
        "log_loss": round(best[0], 4), "table": table, "threshold_found": found,
    }


# --------------------------------------------------------------------------- the gate
@dataclass
class Gate:
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [c["detail"] for c in self.checks if not c["ok"]]


def apply_gate(
    metrics: dict[str, Any], previous: dict[str, Any] | None = None, *, floor: float = PRECISION_FLOOR
) -> Gate:
    """``metrics`` from ``evaluate_model`` on the held-out set; ``previous`` the same numbers for
    the model currently in the repo, on the SAME held-out set (None = no model yet)."""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("enough_eval", metrics["n"] >= MIN_EVAL,
        f"held-out set has {metrics['n']} sentences (need >= {MIN_EVAL})")
    add("enough_fires", metrics["fires"] >= MIN_FIRES,
        f"classifier answered {metrics['fires']} held-out sentences at threshold "
        f"{metrics['threshold']} (need >= {MIN_FIRES} for the precision figure to mean anything)")
    add("precision", metrics["precision"] >= floor,
        f"precision at threshold {metrics['threshold']} is {metrics['precision'] * 100:.1f}% "
        f"(need >= {floor * 100:.0f}%)")
    add("beats_rules", metrics["combined_accuracy"] >= metrics["rules_accuracy"],
        f"live-path accuracy {metrics['combined_accuracy']}% vs rules baseline "
        f"{metrics['rules_accuracy']}%")
    if previous is not None:
        add("beats_previous_model", metrics["combined_accuracy"] >= previous["combined_accuracy"]
            and metrics["precision"] >= previous["precision"] - 1e-9,
            f"live-path {metrics['combined_accuracy']}% / precision {metrics['precision'] * 100:.1f}% "
            f"vs current model {previous['combined_accuracy']}% / {previous['precision'] * 100:.1f}%")
    return Gate(all(c["ok"] for c in checks), checks)


# --------------------------------------------------------------------------- pipeline
@dataclass
class TrainResult:
    model: IntentClassifier
    version: dict[str, Any]
    metrics: dict[str, Any]
    gate: Gate
    written: bool = False


def run_training(
    *,
    cfg: TrainConfig | None = None,
    threshold: float | None = None,
    labels_path: Path | str | None = None,
    model_path: Path | str | None = None,
    version_path: Path | str | None = None,
    write: bool = True,
    **data_kw: Any,
) -> TrainResult:
    cfg = cfg or TrainConfig()
    mp, vp = Path(model_path or MODEL_PATH), Path(version_path or VERSION_PATH)
    train, gold, held = build_training_set(labels_path, seed=cfg.seed, **data_kw)
    cv: dict[str, Any] | None = None
    if threshold is None:
        cfg, threshold, cv = cross_validate(train, gold, cfg)
    model = train_classifier(train, cfg)
    metrics = evaluate_model(model, held, threshold)
    previous = None
    if mp.exists() and load_version(vp):
        try:
            previous = evaluate_model(IntentClassifier.loads(mp.read_text(encoding="utf-8")), held,
                                      float(load_version(vp)["threshold"]))  # type: ignore[index]
        except (OSError, ValueError, KeyError, TypeError):
            previous = None
    gate = apply_gate(metrics, previous)
    blob = model.dumps()
    version = {
        "format": 1,
        "code_version": CODE_VERSION,
        "model_file": mp.name,
        "model_sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
        "data_hash": data_hash(train, held),
        "train_count": len(train),
        "train_by_source": dict(sorted(Counter(e.source for e in train).items())),
        "train_by_intent": dict(sorted(Counter(e.intent for e in train).items())),
        "eval_count": len(held),
        "seed": cfg.seed,
        "alpha": cfg.alpha,
        "beta": cfg.beta,
        "threshold": threshold,
        "threshold_source": "cross_validation" if cv is not None else "cli",
        "cross_validation": cv,
        "metrics": {k: v for k, v in metrics.items() if k != "misses"},
        "gate": {"passed": gate.passed, "checks": gate.checks},
        "data_note": "repo data only: held-out labelled sentences, playbook test rows, persona "
        "replies, deterministic synthetic templates; no real call data",
        "unknown_intents": sorted(INTENTS - set(model.classes)),
    }
    res = TrainResult(model, version, metrics, gate)
    if write and gate.passed:
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(blob, encoding="utf-8")
        vp.write_text(json.dumps(version, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                      encoding="utf-8")
        res.written = True
    return res
