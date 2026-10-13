"""``friday learn report | label | eval | fewshot`` (wired from friday/cli.py).

    friday learn report [--top N]                  the review queue from var/learning
    friday learn label "TEXT" INTENT [--note ...]  add a labelled example (unknown intent refused)
    friday learn eval [--update-baseline]          score the heuristic; exit 1 on regression
    friday learn fewshot [--intents A,B] [-k N]    few-shot lines for the understanding prompt
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
    print("usage: friday learn report|label|eval|fewshot")
    return 2
