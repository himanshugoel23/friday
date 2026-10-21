# ruff: noqa: E501
"""Training / evaluation data for the intent classifier. Repo data ONLY, never real calls.

Sources (every one is synthetic or hand-written and already in this public repo):

* ``labels``   the labelled set ``friday/playbooks/learning/labels.yaml``. A fixed, content-hashed
               share (``EVAL_BUCKETS`` of 5) is the HELD-OUT EVALUATION SET: it is never trained on.
* ``tests``    ``(step, text, INTENT)`` rows in the playbook tests (hand-written expectations).
* ``personas`` the simulated-business replies in ``playbooks/**/*.personas.yaml``, labelled by the
               rules ONLY where the rules are confident (so they teach the model the paraphrases
               of what the audited rules already decide, nothing the rules are unsure about).
* ``synth``    the deterministic augmentation in ``friday/learning/synth.py`` (templates; no model).

``var/`` (the real call learning log) is never read here: the repo is public and that file holds
real, even if masked, vendor speech.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from friday.learning.labels import Label, load_labels
from friday.playbooks.classifier import normalise_text
from friday.playbooks.intents import INTENTS

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK_DIR = REPO_ROOT / "friday" / "playbooks"
TEST_DIR = REPO_ROOT / "tests" / "playbooks"
EVAL_BUCKETS = 2  # of 5: ~40% of the labelled set is held out for evaluation
SOURCE_WEIGHT = {"labels": 3.0, "tests": 2.0, "personas": 1.0, "synth": 1.0}


@dataclass(frozen=True)
class Example:
    text: str
    intent: str
    source: str

    @property
    def weight(self) -> float:
        return SOURCE_WEIGHT.get(self.source, 1.0)


def bucket(text: str) -> int:
    """Stable 0-4 bucket of a sentence (by its normalised text, so spelling-only copies share it)."""
    return hashlib.sha1(normalise_text(text).encode("utf-8")).digest()[0] % 5


def split_labels(labels: list[Label]) -> tuple[list[Label], list[Label]]:
    """(train part, held-out evaluation part). Same text -> same side, in every run."""
    train = [lb for lb in labels if bucket(lb.text) >= EVAL_BUCKETS]
    held = [lb for lb in labels if bucket(lb.text) < EVAL_BUCKETS]
    return train, held


def _tests_examples(test_dir: Path) -> list[Example]:
    """``("S2", "text", "INTENT")`` and ``("text", "INTENT")`` tuples in the playbook tests."""
    out: list[Example] = []
    if not test_dir.is_dir():
        return out
    for f in sorted(test_dir.glob("test_*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Tuple):
                continue
            vals = [e.value for e in node.elts if isinstance(e, ast.Constant)]
            if len(vals) != len(node.elts) or not all(isinstance(v, str) for v in vals):
                continue
            if len(vals) == 3 and vals[2] in INTENTS and vals[1].strip():
                out.append(Example(vals[1], vals[2], "tests"))
    return out


def _walk_strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [s for x in node for s in _walk_strings(x)]
    if isinstance(node, dict):
        got = [s for k in ("say", "text") for s in _walk_strings(node.get(k))]
        return got
    return []


def _persona_examples(playbook_dir: Path) -> list[Example]:
    from friday.playbooks.understand import heuristic

    out: list[Example] = []
    for f in sorted(playbook_dir.glob("**/*.personas.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        extended = f.parent.name == "pending"
        for p in data.get("personas") or []:
            texts: list[str] = []
            for v in (p.get("replies") or {}).values():
                texts += _walk_strings(v)
            texts += _walk_strings(p.get("default"))
            for t in texts:
                t = (t or "").strip()
                if not t or t.startswith("<"):
                    continue
                u = heuristic(t, known={"extended": True} if extended else {})
                if u.confident and u.intent in INTENTS:
                    out.append(Example(t, u.intent, "personas"))
    return out


def gold_examples(
    labels_path: Path | str | None = None, test_dir: Path | None = None
) -> tuple[list[Example], list[Label]]:
    """(gold training examples: labels train part + tests, held-out labels). A training sentence
    that also sits in the held-out set (after normalisation) is dropped from training."""
    train_labels, held = split_labels(load_labels(labels_path))
    held_keys = {normalise_text(lb.text) for lb in held}
    ex = [Example(lb.text, lb.intent, "labels") for lb in train_labels]
    ex += _tests_examples(test_dir or TEST_DIR)
    return [e for e in ex if normalise_text(e.text) not in held_keys], held


def build_training_set(
    labels_path: Path | str | None = None,
    *,
    test_dir: Path | None = None,
    playbook_dir: Path | None = None,
    synth: bool = True,
    seed: int = 7,
) -> tuple[list[Example], list[Example], list[Label]]:
    """(all training examples, gold-only training examples, held-out evaluation labels).
    Deduplicated by (normalised text, intent); a text with two intents keeps the gold one; the
    held-out sentences are removed from every source. Order is deterministic."""
    gold, held = gold_examples(labels_path, test_dir)
    held_keys = {normalise_text(lb.text) for lb in held}
    allx: list[Example] = list(gold)
    allx += _persona_examples(playbook_dir or PLAYBOOK_DIR)
    if synth:
        from friday.learning.synth import generate

        allx += [Example(t, i, "synth") for t, i in generate(seed)]
    seen: dict[str, Example] = {}
    for e in allx:
        k = normalise_text(e.text)
        if not k or k in held_keys:
            continue
        prev = seen.get(k)
        if prev is None or (prev.source == "synth" and e.source != "synth") or (
            prev.source == "personas" and e.source in ("labels", "tests")
        ):
            seen[k] = e
    out = sorted(seen.values(), key=lambda e: (e.intent, normalise_text(e.text)))
    gold_keys = {normalise_text(g.text) for g in gold}
    gold_out = [e for e in out if normalise_text(e.text) in gold_keys and e.source in ("labels", "tests")]
    return out, gold_out, held


def data_hash(train: list[Example], held: list[Label]) -> str:
    """One hash over exactly what the model was trained on and judged on."""
    h = hashlib.sha256()
    for e in sorted(train, key=lambda e: (e.intent, e.text, e.source)):
        h.update(f"T\t{e.source}\t{e.intent}\t{e.text}\n".encode())
    for lb in sorted(held, key=lambda x: (x.intent, x.text)):
        h.update(f"E\t{lb.intent}\t{lb.text}\n".encode())
    return h.hexdigest()
