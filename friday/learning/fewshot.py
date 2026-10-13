"""Few-shot lines for the understanding prompt, from the labelled set."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from friday.learning.labels import load_labels


def export_fewshot(
    intent_list: Iterable[str] | None = None, k: int = 3, path: Path | str | None = None
) -> list[str]:
    """Up to ``k`` examples per intent, as ``reply: "TEXT" -> INTENT``. Stable order: intents
    sorted by name, examples in file order, duplicates dropped. Deterministic."""
    wanted = None if intent_list is None else set(intent_list)
    by: dict[str, list[str]] = {}
    for lb in load_labels(path):
        if wanted is not None and lb.intent not in wanted:
            continue
        if not lb.text.strip():
            continue
        bucket = by.setdefault(lb.intent, [])
        if lb.text not in bucket and len(bucket) < max(0, k):
            bucket.append(lb.text)
    return [f'reply: "{t}" -> {i}' for i in sorted(by) for t in by[i]]
