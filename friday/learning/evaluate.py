"""Score the heuristic understanding on the labelled set and guard against regressions.

``regression`` = any intent whose accuracy dropped vs the stored baseline, or overall accuracy
below baseline minus 0.5 points. The baseline is ``friday/playbooks/learning/baseline.json``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.learning.labels import LEARNING_DIR, Label, load_labels
from friday.playbooks.understand import heuristic

BASELINE_PATH = LEARNING_DIR / "baseline.json"
TOLERANCE_POINTS = 0.5


@dataclass
class Report:
    total: int
    correct: int
    per_intent: dict[str, dict[str, int]]
    mistakes: list[dict[str, str]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return round(100.0 * self.correct / self.total, 2) if self.total else 0.0

    def intent_accuracy(self) -> dict[str, float]:
        return {
            k: round(100.0 * v["correct"] / v["total"], 2)
            for k, v in sorted(self.per_intent.items()) if v["total"]
        }

    def to_baseline(self) -> dict[str, Any]:
        return {"overall": self.accuracy, "per_intent": self.intent_accuracy(), "total": self.total}


def predict(text: str) -> str:
    """The production heuristic with the vendor (extended) intents switched on."""
    return heuristic(text, known={"extended": True}).intent


def evaluate(labels: list[Label] | None = None) -> Report:
    labels = load_labels() if labels is None else labels
    per: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    mistakes: list[dict[str, str]] = []
    correct = 0
    for lb in labels:
        got = predict(lb.text)
        per[lb.intent]["total"] += 1
        if got == lb.intent:
            per[lb.intent]["correct"] += 1
            correct += 1
        else:
            mistakes.append({"text": lb.text, "expected": lb.intent, "got": got})
    return Report(len(labels), correct, dict(per), mistakes)


def load_baseline(path: Path | str | None = None) -> dict[str, Any] | None:
    p = Path(path) if path else BASELINE_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_baseline(report: Report, path: Path | str | None = None) -> Path:
    p = Path(path) if path else BASELINE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report.to_baseline(), indent=2, sort_keys=True) + "\n",
                 encoding="utf-8")
    return p


def regressions(report: Report, baseline: dict[str, Any] | None) -> list[str]:
    """Human-readable regression reasons; empty = fine (or no baseline yet)."""
    if not baseline:
        return []
    out: list[str] = []
    if report.accuracy < float(baseline.get("overall", 0)) - TOLERANCE_POINTS:
        out.append(f"overall {report.accuracy} < baseline {baseline['overall']} - "
                   f"{TOLERANCE_POINTS}")
    now = report.intent_accuracy()
    for intent, was in sorted((baseline.get("per_intent") or {}).items()):
        if intent in now and now[intent] < float(was):
            out.append(f"{intent}: {now[intent]} < baseline {was}")
    return out


def format_report(report: Report, reasons: list[str], baseline: dict[str, Any] | None) -> str:
    lines = [f"overall: {report.correct}/{report.total} = {report.accuracy}%"
             + (f" (baseline {baseline['overall']}%)" if baseline else " (no baseline)")]
    for intent, acc in report.intent_accuracy().items():
        v = report.per_intent[intent]
        lines.append(f"  {intent:<20} {acc:6.1f}%  ({v['correct']}/{v['total']})")
    if report.mistakes:
        lines.append("mistakes:")
        lines += [f"  [{m['expected']} -> {m['got']}] {m['text']}" for m in report.mistakes]
    lines += [f"REGRESSION: {r}" for r in reasons]
    return "\n".join(lines)
