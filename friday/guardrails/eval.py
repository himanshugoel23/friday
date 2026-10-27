# ruff: noqa: E501
"""Red-team evaluation and the regression gate for the guardrails (``friday guardrails eval``).

The corpus (``redteam.txt``, every message invented) is run through the engine with every new
category ON and the rate limiter OFF (so one message never mutes the next). Roughly a quarter of
the lines, chosen by a hash of the text, are the HELD-OUT split: write rules against the rest, then
check the held-out split before trusting a change. ``gate.json`` holds the floors; a change that
lowers a number below a floor fails the test (like the intent classifier's gate).

Honest limit: the rules and the first version of the corpus were written together, so the first
numbers are optimistic. Add every real miss from the pilot (docs/CHATBOT_GUARDRAILS.md layer 5) as a
new line.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from friday.guardrails.engine import Guardrails, GuardrailsConfig
from friday.guardrails.models import Context

HERE = Path(__file__).parent
CORPUS = HERE / "redteam.txt"
GATE = HERE / "gate.json"
# categories a harmless message may land in without being "stopped"
PASS_THROUGH = {"in_scope", "small_talk", "factual"}


@dataclass(frozen=True)
class Case:
    expected: str
    lang: str
    tag: str
    text: str

    @property
    def holdout(self) -> bool:
        return int(hashlib.sha256(self.text.encode()).hexdigest(), 16) % 4 == 0


def load_corpus(path: Path = CORPUS) -> list[Case]:
    cases = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        expected, lang, tag, text = (p.strip() for p in raw.split("|", 3))
        cases.append(Case(expected, lang, tag, text))
    return cases


@dataclass
class Report:
    total: int = 0
    correct: int = 0
    by_category: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    misses: list[tuple[Case, str, str]] = field(default_factory=list)  # (case, got category, rule)
    false_positives: int = 0  # harmless messages that were stopped
    in_scope_total: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def recall(self, category: str) -> float:
        ok, n = self.by_category[category]
        return ok / n if n else 1.0

    def lines(self) -> list[str]:
        out = [f"overall {self.correct}/{self.total} = {self.accuracy:.1%}; "
               f"harmless messages wrongly stopped {self.false_positives}/{self.in_scope_total}"]
        for cat in sorted(self.by_category):
            ok, n = self.by_category[cat]
            out.append(f"  {cat:18s} {ok}/{n}")
        for case, got, rule in self.misses:
            out.append(f"  MISS expected {case.expected} got {got} ({rule}): {case.text!r}")
        return out


def evaluate(cases: list[Case] | None = None, *, holdout: bool | None = None,
             config: GuardrailsConfig | None = None) -> Report:
    """Run the corpus. ``holdout`` True/False picks that split, None runs everything."""
    cfg = config or GuardrailsConfig(new_categories=True, rate_limit=False, output_filter=True,
                                     login_otp_in_chat=False)
    rep = Report()
    for case in cases if cases is not None else load_corpus():
        if holdout is not None and case.holdout != holdout:
            continue
        lang = "hi" if case.lang == "hindi" else case.lang
        d = Guardrails(cfg).check(case.text, Context(user_id="eval", lang=lang))
        got = d.category.value
        rep.total += 1
        rep.by_category[case.expected][1] += 1
        if case.expected == "in_scope":
            rep.in_scope_total += 1
            ok = got in PASS_THROUGH and not d.handled
            if not ok:
                rep.false_positives += 1
        else:
            ok = got == case.expected
        if ok:
            rep.correct += 1
            rep.by_category[case.expected][0] += 1
        else:
            rep.misses.append((case, got, d.rule))
    return rep


def load_gate() -> dict[str, float]:
    return json.loads(GATE.read_text())


def check_gate(full: Report, held: Report, gate: dict[str, float] | None = None) -> list[str]:
    """Problems against the committed floors (empty list = pass)."""
    g = gate or load_gate()
    problems = []
    if full.accuracy < g["min_overall"]:
        problems.append(f"overall {full.accuracy:.1%} < {g['min_overall']:.1%}")
    if held.accuracy < g["min_holdout"]:
        problems.append(f"held-out {held.accuracy:.1%} < {g['min_holdout']:.1%}")
    if full.false_positives > g["max_false_positives"]:
        problems.append(f"harmless messages stopped {full.false_positives} > {g['max_false_positives']:.0f}")
    for cat in list(full.by_category):
        if cat != "in_scope" and full.recall(cat) < g["min_category_recall"]:
            problems.append(f"{cat} recall {full.recall(cat):.0%} < {g['min_category_recall']:.0%}")
    if full.total < g["min_cases"]:
        problems.append(f"corpus has {full.total} cases < {g['min_cases']:.0f}")
    return problems


def run_cli() -> int:
    full, held = evaluate(), evaluate(holdout=True)
    for line in full.lines():
        print(line)
    print(f"held-out split: {held.correct}/{held.total} = {held.accuracy:.1%}")
    problems = check_gate(full, held)
    for p in problems:
        print("GATE FAIL:", p)
    print("gate:", "FAIL" if problems else "pass")
    return 1 if problems else 0
