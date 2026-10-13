"""The review queue: what the listening side should be taught next.

Groups logged utterances by normalised text (lowercase, no punctuation, digits -> ``#``) and
ranks the groups: unhandled first, then low confidence, then how often it was heard.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.learning.log import log_path

_PUNCT = re.compile(r"[^\w\s#<>]", re.UNICODE)


def normalise(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"\d", "#", t)
    t = _PUNCT.sub(" ", t.replace("_", " "))
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class QueueRow:
    key: str
    example: str
    count: int = 0
    unhandled: int = 0
    low_confidence: int = 0
    intents: Counter[str] = field(default_factory=Counter)
    steps: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.key, "example": self.example, "count": self.count,
            "unhandled": self.unhandled, "low_confidence": self.low_confidence,
            "intents": dict(self.intents.most_common()), "steps": dict(self.steps.most_common()),
        }


def read_log(path: Path | str | None = None) -> list[dict[str, Any]]:
    p = Path(path) if path else log_path()
    rows: list[dict[str, Any]] = []
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("text"):
                    rows.append(d)
    except OSError:
        pass
    return rows


def build_queue(path: Path | str | None = None) -> list[QueueRow]:
    groups: dict[str, QueueRow] = {}
    for d in read_log(path):
        key = normalise(str(d["text"]))
        if not key:
            continue
        g = groups.setdefault(key, QueueRow(key=key, example=str(d["text"])))
        g.count += 1
        g.unhandled += 1 if d.get("unhandled") else 0
        g.low_confidence += 0 if d.get("confident", True) else 1
        g.intents[str(d.get("intent", "UNCLEAR"))] += 1
        g.steps[str(d.get("step", ""))] += 1
    return sorted(
        groups.values(),
        key=lambda r: (r.unhandled == 0, r.low_confidence == 0, -r.count, r.key),
    )


def top(n: int = 20, path: Path | str | None = None) -> list[QueueRow]:
    return build_queue(path)[: max(0, n)]
