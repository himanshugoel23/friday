"""The labelled evaluation set: ``friday/playbooks/learning/labels.yaml``.

Each row is ``{text, intent, note?}``. Synthetic or reviewed-and-anonymised sentences only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from friday.playbooks.intents import INTENTS

LEARNING_DIR = Path(__file__).resolve().parents[1] / "playbooks" / "learning"
LABELS_PATH = LEARNING_DIR / "labels.yaml"


class LabelError(ValueError):
    pass


@dataclass(frozen=True)
class Label:
    text: str
    intent: str
    note: str = ""


def validate(text: str, intent: str) -> None:
    if intent not in INTENTS:
        raise LabelError(f"unknown intent {intent!r}; known: {', '.join(sorted(INTENTS))}")
    if not (text or "").strip():
        raise LabelError("text is empty")


def load_labels(path: Path | str | None = None) -> list[Label]:
    p = Path(path) if path else LABELS_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise LabelError(f"{p}: expected a list of {{text, intent}} rows")
    out: list[Label] = []
    for i, row in enumerate(data):
        if not isinstance(row, dict) or "text" not in row or "intent" not in row:
            raise LabelError(f"{p}: row {i + 1} needs text and intent")
        text, intent = str(row["text"]), str(row["intent"])
        validate(text or "x", intent)
        out.append(Label(text=text, intent=intent, note=str(row.get("note") or "")))
    return out


def add_label(text: str, intent: str, note: str = "", path: Path | str | None = None) -> Label:
    """Append one label (text append: the file's comments survive). Refuses unknown intents and
    exact duplicates."""
    validate(text, intent)
    p = Path(path) if path else LABELS_PATH
    text = text.strip()
    if p.exists() and any(lb.text == text for lb in load_labels(p)):
        raise LabelError("this text is already labelled")
    row: dict[str, str] = {"text": text, "intent": intent}
    if note:
        row["note"] = note
    chunk = yaml.safe_dump([row], allow_unicode=True, default_flow_style=False, width=10_000)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    sep = "" if not existing or existing.endswith("\n") else "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(sep + chunk)
    return Label(text=text, intent=intent, note=note)
