"""``friday eval``: run every scenario, score it, compare with the saved baseline.

Exit codes: 0 fine, 1 regression (a check that passed in the baseline now fails, or a
scenario's score dropped; with ``--strict`` any failing check), 2 cannot run.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.quality.checks import CHECKS, CheckResult, run_checks
from friday.quality.harness import run_scenario
from friday.quality.scenarios import LANGUAGES, Scenario, Utterance

BASELINE_PATH = Path(__file__).with_name("baseline.json")
BASELINE_VERSION = 1
EPS = 1e-9


@dataclass
class ScenarioScore:
    id: str
    title: str
    checks: list[CheckResult]
    judge: dict[str, int] | None = None
    transcript: list[tuple[str, str]] = field(default_factory=list)

    @property
    def score(self) -> float:
        return sum(c.passed for c in self.checks) / len(self.checks) if self.checks else 0.0

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


@dataclass
class EvalReport:
    scores: list[ScenarioScore]

    @property
    def total(self) -> float:
        return sum(s.score for s in self.scores) / len(self.scores) if self.scores else 0.0

    def as_baseline(self) -> dict[str, Any]:
        return {
            "version": BASELINE_VERSION,
            "scenarios": {
                s.id: {"score": round(s.score, 4), "checks": {c.name: c.passed for c in s.checks}}
                for s in self.scores
            },
        }


async def run_eval(
    scenarios: list[Scenario], *, live: bool = False, judge_llm: Any = None
) -> EvalReport:
    out: list[ScenarioScore] = []
    for sc in scenarios:
        data = await run_scenario(sc, live=live)
        score = ScenarioScore(
            sc.id, sc.title, run_checks(data),
            transcript=_transcript(data),
        )
        if judge_llm is not None and data.ok:
            from friday.quality.judge import judge

            judged = await judge(judge_llm, score.transcript)
            score.judge = judged.scores if judged else None
        out.append(score)
    return EvalReport(out)


def _transcript(data: Any) -> list[tuple[str, str]]:
    if data.result is None:
        return []
    return [(t.speaker.value, t.text) for t in data.result.transcript.turns]


# ------------------------------------------------------------------ baseline
def load_baseline(path: Path = BASELINE_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if data.get("version") == BASELINE_VERSION else None


def save_baseline(report: EvalReport, path: Path = BASELINE_PATH) -> None:
    path.write_text(json.dumps(report.as_baseline(), indent=2, sort_keys=True) + "\n", "utf-8")


def find_regressions(report: EvalReport, baseline: dict[str, Any] | None) -> list[str]:
    """Plain-language list of what got worse vs the baseline (empty = no regression)."""
    if not baseline:
        return []
    base = baseline.get("scenarios", {})
    problems: list[str] = []
    for s in report.scores:
        old = base.get(s.id)
        if old is None:
            continue  # a new scenario cannot regress
        now = {c.name: c.passed for c in s.checks}
        for name, was_ok in old.get("checks", {}).items():
            if was_ok and now.get(name) is False:
                detail = next((c.detail for c in s.checks if c.name == name), "")
                extra = f" ({detail})" if detail else ""
                problems.append(f"{s.id}: '{name}' passed before, fails now{extra}")
        if s.score + EPS < float(old.get("score", 0.0)) and not any(s.id in p for p in problems):
            problems.append(f"{s.id}: score fell from {old['score']:.2f} to {s.score:.2f}")
    return problems


# ------------------------------------------------------------------ output
def render_table(report: EvalReport, baseline: dict[str, Any] | None = None) -> str:
    names = list(CHECKS)
    short = {n: n[:11] for n in names}
    base = (baseline or {}).get("scenarios", {})
    idw = max([len(s.id) for s in report.scores] + [8])
    cols = " ".join(f"{short[n]:<11}" for n in names)
    head = f"{'scenario':<{idw}}  score  {cols}  vs base"
    lines = [head, "-" * len(head)]
    for s in report.scores:
        by = {c.name: c for c in s.checks}
        marks = " ".join(
            f"{('ok' if by[n].passed else 'FAIL') if n in by else '-':<11}" for n in names
        )
        delta = ""
        if s.id in base:
            diff = s.score - float(base[s.id].get("score", 0.0))
            delta = "same" if abs(diff) < EPS else f"{diff:+.2f}"
        elif baseline:
            delta = "new"
        lines.append(f"{s.id:<{idw}}  {s.score:>4.0%}  {marks}  {delta}")
    lines.append("-" * len(head))
    lines.append(f"{'TOTAL':<{idw}}  {report.total:>4.0%}")
    fails = [(s, c) for s in report.scores for c in s.failed]
    if fails:
        lines.append("\nFailing checks:")
        for s, c in fails:
            lines.append(f"  {s.id} / {c.name}" + (f": {c.detail}" if c.detail else ""))
    judged = [s for s in report.scores if s.judge]
    if judged:
        lines.append("\nLLM judge (1-5, read, not gated):")
        for s in judged:
            lines.append(f"  {s.id}: " + ", ".join(f"{k} {v}" for k, v in (s.judge or {}).items()))
    return "\n".join(lines)


def common_language(langs: list[str]) -> str:
    return Counter(langs).most_common(1)[0][0] if langs else "hinglish"


def scenario_from_stored(call: Any) -> Scenario:
    """A labelled real call (redacted transcript) as a new scenario: the caller's lines are the
    script; the language is what the caller ended in; the labels travel with it."""
    callee = [t for t in call.transcript if t.get("speaker") == "callee"]
    langs = [x if x in LANGUAGES else "hinglish" for x in (t.get("language") for t in callee)]
    language = common_language(langs)
    script = [Utterance("say", t["text"], lang) for t, lang in zip(callee, langs, strict=True)]
    expect: dict[str, Any] = {"language": langs[-1] if langs else language}
    return Scenario(
        id=f"call_{call.call_id[:12]}",
        title="from a labelled real call: " + ", ".join(call.labels),
        caller="new" if call.meta.get("onboarded") else "returning", language=language,
        script=script, expect=expect,
        meta={"labels": list(call.labels), "source_call": call.call_id},
    )
