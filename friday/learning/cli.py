# ruff: noqa: E501
"""``friday learn report | label | eval | fewshot | train-classifier | eval-classifier``
(wired from friday/cli.py).

    friday learn report [--top N]                  the review queue from var/learning
    friday learn label "TEXT" INTENT [--note ...]  add a labelled example (unknown intent refused)
    friday learn eval [--update-baseline]          score the heuristic; exit 1 on regression
    friday learn fewshot [--intents A,B] [-k N]    few-shot lines for the understanding prompt
    friday learn train-classifier [--dry-run]      train the small intent classifier; writes the
                                                   model ONLY if the regression gate passes
    friday learn eval-classifier [--model PATH]    accuracy per intent, confusion pairs, comparison
                                                   with the rules baseline, gate verdict
    friday learn train-eot [--dry-run]             train the semantic end-of-turn model (writes it
                                                   ONLY if the regression gate passes)
    friday learn eval-eot [--split test|train|all] accuracy / precision / recall per class, false-cut
                                                   rate, mean added delay; rules-only baseline beside it
"""

from __future__ import annotations

import argparse
from typing import Any


def register(sub: Any) -> None:
    ln = sub.add_parser("learn", help="listening-side learning loop: report, label, eval, fewshot")
    s = ln.add_subparsers(dest="learn_cmd")
    rp = s.add_parser("report", help="the review queue (unhandled / low confidence first)")
    rp.add_argument("--top", type=int, default=20)
    rp.add_argument("--log", default=None, help="utterance log (default var/learning)")
    lb = s.add_parser("label", help="add a labelled example to labels.yaml")
    lb.add_argument("text")
    lb.add_argument("intent")
    lb.add_argument("--note", default="")
    ev = s.add_parser("eval", help="score the heuristic on the labelled set")
    ev.add_argument("--update-baseline", action="store_true")
    fs = s.add_parser("fewshot", help="few-shot lines from the labelled set")
    fs.add_argument("--intents", default=None, help="comma list (default all)")
    fs.add_argument("-k", type=int, default=3)
    tc = s.add_parser("train-classifier", help="train the intent classifier (gate-protected)")
    tc.add_argument("--dry-run", action="store_true", help="train and report, write nothing")
    tc.add_argument("--seed", type=int, default=7, help="seed of the synthetic data")
    tc.add_argument("--threshold", type=float, default=None,
                    help="confidence threshold (default: chosen by cross-validation)")
    tc.add_argument("--model", default=None, help="model file (default: the repo's)")
    te = s.add_parser("train-eot", help="train the semantic end-of-turn model (gate-protected)")
    te.add_argument("--dry-run", action="store_true", help="train and report, write nothing")
    te.add_argument("--seed", type=int, default=7, help="seed of the synthetic data")
    ee = s.add_parser("eval-eot", help="score the end-of-turn detector on the hand-written list")
    ee.add_argument("--model", default=None, help="model file (default: the repo's)")
    ee.add_argument("--threshold", type=float, default=None, help="default: the version file's")
    ee.add_argument("--split", choices=("test", "train", "all"), default="test",
                    help="test = the held-out set (default); train/all include trained-on rows")
    ee.add_argument("--mistakes", action="store_true", help="list the wrong and the unsure ones")
    ec = s.add_parser("eval-classifier", help="score the classifier on the held-out labels")
    ec.add_argument("--model", default=None)
    ec.add_argument("--threshold", type=float, default=None,
                    help="default: the threshold in the version file")
    ec.add_argument("--all-labels", action="store_true",
                    help="score ALL labels (includes the training share: optimistic)")


def run(args: argparse.Namespace) -> int:
    cmd = getattr(args, "learn_cmd", None)
    if cmd == "report":
        from friday.learning.queue import top

        rows = top(args.top, args.log)
        if not rows:
            print("review queue is empty")
        for r in rows:
            print(f"{r.count:>4}x  unhandled={r.unhandled} low_conf={r.low_confidence} "
                  f"intents={dict(r.intents)}  {r.example!r}")
        return 0
    if cmd == "label":
        from friday.learning.labels import LabelError, add_label

        try:
            lb = add_label(args.text, args.intent, args.note)
        except LabelError as e:
            print(f"refused: {e}")
            return 2
        print(f"added: {lb.text!r} -> {lb.intent}")
        return 0
    if cmd == "eval":
        from friday.learning import evaluate as ev

        rep = ev.evaluate()
        base = ev.load_baseline()
        reasons = ev.regressions(rep, base)
        print(ev.format_report(rep, reasons, base))
        if args.update_baseline:
            print(f"baseline written: {ev.save_baseline(rep)}")
            return 0
        return 1 if reasons else 0
    if cmd == "fewshot":
        from friday.learning.fewshot import export_fewshot

        intents = args.intents.split(",") if args.intents else None
        print("\n".join(export_fewshot(intents, args.k)))
        return 0
    if cmd == "train-classifier":
        return _train_classifier(args)
    if cmd == "eval-classifier":
        return _eval_classifier(args)
    if cmd == "train-eot":
        return _train_eot(args)
    if cmd == "eval-eot":
        return _eval_eot(args)
    print("usage: friday learn report|label|eval|fewshot|train-classifier|eval-classifier"
          "|train-eot|eval-eot")
    return 2


def _train_classifier(args: argparse.Namespace) -> int:
    from pathlib import Path

    from friday.learning.classifier_train import TrainConfig, format_eval, run_training
    from friday.playbooks.classifier import MODEL_PATH, VERSION_PATH

    model = Path(args.model) if args.model else MODEL_PATH
    version = model.with_name(model.stem + ".version.json") if args.model else VERSION_PATH
    res = run_training(cfg=TrainConfig(seed=args.seed), threshold=args.threshold,
                       model_path=model, version_path=version, write=not args.dry_run)
    v = res.version
    print(f"training sentences: {v['train_count']} {v['train_by_source']}")
    print(f"data hash: {v['data_hash'][:16]}   alpha={v['alpha']} beta={v['beta']}   "
          f"threshold={v['threshold']} ({v['threshold_source']})")
    print(format_eval(res.metrics))
    for c in res.gate.checks:
        print(f"  gate {'ok  ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}")
    if not res.gate.passed:
        print("REFUSED: the model is NOT written (regression gate failed).")
        return 1
    print(f"written: {model} ({len(res.model.dumps())} bytes) and {version.name}"
          if res.written else "gate passed (dry run: nothing written)")
    return 0


def _eval_classifier(args: argparse.Namespace) -> int:
    from pathlib import Path

    from friday.learning.classifier_data import split_labels
    from friday.learning.classifier_train import apply_gate, evaluate_model, format_eval
    from friday.learning.labels import load_labels
    from friday.playbooks.classifier import (
        MODEL_PATH,
        VERSION_PATH,
        IntentClassifier,
        load_version,
    )

    model_path = Path(args.model) if args.model else MODEL_PATH
    version_path = (
        model_path.with_name(model_path.stem + ".version.json") if args.model else VERSION_PATH
    )
    try:
        model = IntentClassifier.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        print(f"no usable model at {model_path} (run: friday learn train-classifier)")
        return 2
    ver = load_version(version_path) or {}
    threshold = args.threshold if args.threshold is not None else float(ver.get("threshold", 0.9))
    labels = load_labels()
    held = labels if args.all_labels else split_labels(labels)[1]
    if args.all_labels:
        print("NOTE: all labels, including the share the model trained on (optimistic)")
    metrics = evaluate_model(model, held, threshold)
    print(format_eval(metrics))
    if ver:
        print(f"model version: data {str(ver.get('data_hash', ''))[:16]}  "
              f"gate_passed={(ver.get('gate') or {}).get('passed')}")
    gate = apply_gate(metrics)
    for c in gate.checks:
        print(f"  gate {'ok  ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}")
    return 0 if gate.passed else 1


def _train_eot(args: argparse.Namespace) -> int:
    from friday.learning.eot_train import TrainConfig, format_eval, run_training

    res = run_training(cfg=TrainConfig(seed=args.seed), write=not args.dry_run)
    v = res.version
    print(f"training rows: {v['train_count']} {v['train_by_source']}   held-out: {v['held_out_count']} "
          f"(never trained on)")
    print(f"data hash: {v['data_hash'][:16]}   alpha={v['alpha']} beta={v['beta']}   "
          f"threshold={v['threshold']} ({v['threshold_source']})")
    print(format_eval(res.baseline, "HELD-OUT, rules only (the baseline):"))
    print(format_eval(res.metrics, "HELD-OUT, rules + trained model:"))
    for c in res.gate.checks:
        print(f"  gate {'ok  ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}")
    if not res.gate.passed:
        print("REFUSED: the model is NOT written (regression gate failed).")
        return 1
    print("written: friday/voice/learning/eot_model.json and eot_model.version.json"
          if res.written else "gate passed (dry run: nothing written)")
    return 0


def _eval_eot(args: argparse.Namespace) -> int:
    from pathlib import Path

    from friday.learning.eot_train import (
        apply_gate,
        evaluate,
        format_eval,
        load_gold,
    )
    from friday.voice.eot import MODEL_PATH, VERSION_PATH, EotModel, SemanticEot, load_version

    model_path = Path(args.model) if args.model else MODEL_PATH
    version_path = (
        model_path.with_name(model_path.stem + ".version.json") if args.model else VERSION_PATH
    )
    try:
        model = EotModel.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        print(f"no usable model at {model_path} (run: friday learn train-eot)")
        return 2
    ver = load_version(version_path) or {}
    thr = args.threshold if args.threshold is not None else float(ver.get("threshold", 0.9))
    train, test = load_gold()
    items = {"test": test, "train": train, "all": train + test}[args.split]
    if args.split != "test":
        print("NOTE: includes rows the model trained on (optimistic)")
    base = evaluate(SemanticEot(None, thr, rules_only=True), items)
    mod = evaluate(SemanticEot(model, thr), items)
    print(format_eval(base, f"{args.split} split, rules only (baseline), threshold {thr}:"))
    print(format_eval(mod, f"{args.split} split, rules + trained model, threshold {thr}:"))
    if args.mistakes:
        for m in mod["mistakes"]:
            print(f"  WRONG  gold={m['gold']:<10} said={m['said']:<10} [{m['type'] or '-'}] {m['text']}")
        for m in mod["unsure"]:
            print(f"  unsure gold={m['gold']:<10} [{m['type'] or '-'}] {m['text']}")
    if ver:
        print(f"model version: data {str(ver.get('data_hash', ''))[:16]}  "
              f"gate_passed={(ver.get('gate') or {}).get('passed')}")
    gate = apply_gate(mod, base, thr)
    for c in gate.checks:
        print(f"  gate {'ok  ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}")
    return 0 if gate.passed else 1
