"""The authoring loop: generate -> validate -> dry-run -> patch, up to ``rounds`` times.

    draft   playbook text + personas text from the backend (a parse failure is retried once)
    check   the EXISTING loader/validator (errors are fed back to the model) plus persona sanity
    dry-run the EXISTING simulator on the generated personas
    patch   failures (unhandled intents, outcomes not as expected, limits, safety) go back to the
            model; safety violations can never be waived

Everything lands in the DRAFTS directory (default ``var/playbook_drafts/<business_type>/``),
never in ``friday/playbooks/data``. Promotion is a separate, confirmed step (promote.py).
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from friday.playbooks import dryrun
from friday.playbooks.authoring import prompt
from friday.playbooks.authoring.backends import AuthorBackend, AuthorRequest
from friday.playbooks.authoring.knowledge import BusinessType, get_business_type
from friday.playbooks.model import (
    DATA_DIR,
    Playbook,
    PlaybookError,
    _Loader,
    parse_text,
    validate_data,
)

DEFAULT_ROUNDS = 3
DEFAULT_DRAFT_ROOT = Path("var/playbook_drafts")
MIN_PERSONAS = 15
MAX_PERSONAS_HARD = 40
CHARS_PER_TOKEN = 3.0  # rough, for the pre-run budget estimate only


class OutputRefused(ValueError):
    """The drafts directory would be inside the real playbook data directory."""


class BudgetExceeded(RuntimeError):
    pass


# =============================================================================== paths
def resolve_draft_dir(root: Path | str | None, business_type: str) -> Path:
    base = Path(root) if root else DEFAULT_DRAFT_ROOT
    base = base.expanduser().resolve()
    data = DATA_DIR.resolve()
    pkg = data.parent
    if base in (data, pkg) or data in base.parents or pkg in base.parents:
        raise OutputRefused(
            f"refusing to write drafts into {base}: drafts never go inside friday/playbooks. "
            "Use the default (var/playbook_drafts) or another folder."
        )
    return base / business_type


# =============================================================================== budget
@dataclass
class BudgetPlan:
    backend: str
    model: str
    live: bool
    rounds: int
    max_calls: int
    max_tokens_per_call: int
    est_input_tokens_per_call: int
    worst_case_cost_inr: float

    @property
    def max_output_tokens(self) -> int:
        return self.max_calls * self.max_tokens_per_call

    def describe(self) -> str:
        if not self.live:
            return (f"Backend: {self.backend}. No model is called, no network, no cost. "
                    f"Up to {self.rounds} improvement round(s).")
        return (
            f"Backend: {self.backend}\n"
            f"Budget (hard limits): at most {self.rounds} improvement round(s) after the first "
            f"draft; at most {self.max_calls} model calls (each reply may be re-asked once if it "
            f"cannot be read); at most {self.max_tokens_per_call} output tokens per call "
            f"({self.max_output_tokens} in total).\n"
            f"Estimated worst-case cost: about Rs {self.worst_case_cost_inr:.0f} "
            f"(~{self.est_input_tokens_per_call} input tokens per call, all output tokens used; "
            "an estimate, not a bill)."
        )


def plan_budget(backend: AuthorBackend, rounds: int) -> BudgetPlan:
    from friday.playbooks.authoring.prompt import system_prompt

    max_calls = 2 * (rounds + 1)
    est_in = int((len(system_prompt()) + 9000) / CHARS_PER_TOKEN)
    if backend.is_live:
        # repair/patch prompts also carry both files (~ the previous output), so add it
        est_total_in = max_calls * (est_in + backend.max_tokens)
        cost = backend.estimate_cost_inr(est_total_in, max_calls * backend.max_tokens)
    else:
        cost = 0.0
    return BudgetPlan(backend.name, backend.model, backend.is_live, rounds, max_calls,
                      backend.max_tokens, est_in, round(cost, 2))


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_inr: float = 0.0
    models: set[str] = field(default_factory=set)


# =============================================================================== checking
def _load_personas_text(text: str) -> dryrun.PersonaFile:
    data = yaml.load(text, Loader=_Loader)  # noqa: S506
    if not isinstance(data, dict):
        raise ValueError("the personas file must be a mapping with version / playbook / personas")
    return dryrun.PersonaFile.model_validate(data)


def check_draft(
    business_type: str, playbook_text: str, personas_text: str
) -> tuple[list[str], Playbook | None, dryrun.PersonaFile | None]:
    """Everything wrong with a draft, using the existing validator. [] means structurally fine."""
    problems: list[str] = []
    pb: Playbook | None = None
    pf: dryrun.PersonaFile | None = None
    try:
        pb = validate_data(parse_text(playbook_text), business_type)
    except PlaybookError as e:
        problems += [f"playbook: {p}" for p in e.problems]
    if pb is not None and pb.id != business_type:
        problems.append(f"playbook: id must be exactly '{business_type}' (got '{pb.id}')")
    try:
        pf = _load_personas_text(personas_text)
    except (yaml.YAMLError, ValidationError, ValueError) as e:
        msg = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()
        ) if isinstance(e, ValidationError) else f"{type(e).__name__}: {str(e)[:300]}"
        problems.append(f"personas: {msg}")
    if pf is not None:
        if pf.playbook != business_type:
            problems.append(
                f"personas: 'playbook:' must be '{business_type}' (got '{pf.playbook}')"
            )
        ids = [p.id for p in pf.personas]
        if len(ids) != len(set(ids)):
            problems.append("personas: duplicate persona ids")
        if len(ids) < MIN_PERSONAS:
            problems.append(
                f"personas: only {len(ids)}; write 20 to 25 realistic businesses (at least "
                f"{MIN_PERSONAS})"
            )
        if len(ids) > MAX_PERSONAS_HARD:
            problems.append(f"personas: {len(ids)} is too many; write 20 to 25")
        problems += _required_safety_tests(pf)
        if pb is not None:
            for per in pf.personas:
                for key in per.replies:
                    if key.split("@")[0] not in pb.lines:
                        problems.append(
                            f"personas.{per.id}: reply key '{key}' is not a line id of the playbook"
                        )
                exp = per.expect.get("outcome")
                if exp and exp not in pb.outcomes:
                    problems.append(f"personas.{per.id}: expects unknown outcome '{exp}'")
    return problems, pb, pf


def _required_safety_tests(pf: dryrun.PersonaFile) -> list[str]:
    """The safety tests every draft must keep, so deleting the failing test cannot waive a
    violation: a stop request, an OTP ask, a wrong number, a rude hang-up, a delegated booking."""
    ps = pf.personas

    def says(p: dryrun.PersonaDef, word: str) -> bool:
        return word in str(p.replies).lower()

    need = {
        "someone who asks not to be called again (stop_request: true)":
            any(p.stop_request for p in ps),
        "someone who asks Friday for an OTP": any(says(p, "otp") for p in ps),
        "a wrong number (expect WRONG_NUMBER)":
            any(p.expect.get("outcome") == "WRONG_NUMBER" for p in ps),
        "someone rude who hangs up": any(says(p, "'hangup': true") for p in ps),
        "a booking the user delegated (brief.delegation_max_price)":
            any(p.brief.get("delegation_max_price") for p in ps),
    }
    return [f"personas: missing the required safety test: {k}" for k, ok in need.items() if not ok]


# =============================================================================== dry run + failures
def _stage_files(business_type: str, playbook_text: str, personas_text: str, workdir: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / f"{business_type}.yaml").write_text(playbook_text, encoding="utf-8")
    (workdir / f"{business_type}.personas.yaml").write_text(personas_text, encoding="utf-8")


async def run_dryrun_on_texts(
    business_type: str, playbook_text: str, personas_text: str, workdir: Path
) -> dryrun.DryRunReport:
    await asyncio.to_thread(_stage_files, business_type, playbook_text, personas_text, workdir)
    return await dryrun.run_dryrun(business_type, directory=workdir)


@dataclass
class Failure:
    persona: str
    title: str
    failed: list[str]
    details: list[str]
    safety: list[str]
    steps: list[str]
    transcript: list[tuple[str, str]]

    def text(self) -> str:
        head = f"persona '{self.persona}' ({self.title}): failed checks {', '.join(self.failed)}"
        lines = [head]
        lines += [f"  detail: {d}" for d in self.details if d]
        if self.safety:
            lines.append("  SAFETY VIOLATION (cannot be waived): " + " | ".join(self.safety))
        lines.append("  steps visited: " + " > ".join(self.steps))
        lines.append("  conversation:")
        lines += [f"    {sp.upper():<7} {tx}" for sp, tx in self.transcript[-14:]]
        return "\n".join(lines)


def collect_failures(report: dryrun.DryRunReport) -> list[Failure]:
    out = []
    for r in report.runs:
        if not r.failed:
            continue
        out.append(
            Failure(r.persona, r.title, list(r.failed),
                    [f"{c}: {r.details.get(c, '')}" for c in r.failed], list(r.safety),
                    list(r.steps), list(r.transcript))
        )
    return out


# =============================================================================== the result
@dataclass
class RoundLog:
    number: int
    action: str  # draft | repair | patch
    found: list[str] = field(default_factory=list)  # what was wrong BEFORE this action
    note: str = ""


@dataclass
class DraftResult:
    business_type: str
    title: str
    out_dir: Path
    backend: str
    live: bool
    model: str
    plan: BudgetPlan
    rounds_allowed: int
    playbook_text: str = ""
    personas_text: str = ""
    pb: Playbook | None = None
    pf: dryrun.PersonaFile | None = None
    problems: list[str] = field(default_factory=list)  # validator problems still open
    report: dryrun.DryRunReport | None = None
    failures: list[Failure] = field(default_factory=list)
    log: list[RoundLog] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    notes: list[str] = field(default_factory=list)
    expect_changes: list[str] = field(default_factory=list)
    removed_personas: list[str] = field(default_factory=list)
    safety_waived: list[str] = field(default_factory=list)
    safety_seen: set[str] = field(default_factory=set)
    unreadable: bool = False
    files: dict[str, Path] = field(default_factory=dict)

    @property
    def safety_violations(self) -> list[tuple[str, str]]:
        return self.report.safety_violations if self.report else []

    @property
    def safety_ok(self) -> bool:
        return (
            self.report is not None
            and not self.safety_violations
            and not self.safety_waived
            and not self.problems
        )

    @property
    def passes(self) -> bool:
        return self.safety_ok and not self.failures

    @property
    def status(self) -> str:
        if self.unreadable or self.pb is None:
            return "failed"
        if self.safety_violations or self.safety_waived:
            return "blocked_safety"
        if self.problems:
            return "failed"
        return "ready_for_review" if self.passes else "needs_work"


# =============================================================================== the loop
Progress = Callable[[str], None]


async def _ask(
    backend: AuthorBackend, usage: Usage, plan: BudgetPlan, req: AuthorRequest,
    personas_required: bool,
) -> prompt.ParsedReply:
    """One model call, retried once if the reply cannot be read."""
    user = req.user
    last_err = ""
    for attempt in (1, 2):
        if usage.calls >= plan.max_calls:
            raise BudgetExceeded(f"the budget of {plan.max_calls} model calls is used up")
        req = AuthorRequest(req.kind, req.business_type, req.system, user, attempt,
                            req.previous_playbook, req.previous_personas)
        reply = await backend.generate(req)
        usage.calls += 1
        usage.input_tokens += reply.input_tokens
        usage.output_tokens += reply.output_tokens
        usage.cost_inr += reply.cost_inr
        if reply.model:
            usage.models.add(reply.model)
        try:
            return prompt.parse_reply(reply.text, personas_required=personas_required)
        except prompt.ReplyParseError as e:
            last_err = str(e)
            user = req.user + "\n\n" + prompt.retry_format_prompt(last_err)
    raise prompt.ReplyParseError(last_err)


def _expectations(pf: dryrun.PersonaFile | None) -> dict[str, str]:
    if pf is None:
        return {}
    return {
        p.id: p.expect.get("outcome") or p.expect.get("call_outcome") or ""
        for p in pf.personas
    }


async def run_draft(
    business_type: str,
    *,
    backend: AuthorBackend,
    out_root: Path | str | None = None,
    rounds: int = DEFAULT_ROUNDS,
    progress: Progress | None = None,
) -> DraftResult:
    say = progress or (lambda _m: None)
    bt: BusinessType = get_business_type(business_type)
    out_dir = resolve_draft_dir(out_root, business_type)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = plan_budget(backend, rounds)
    res = DraftResult(business_type, bt.title, out_dir, backend.name, backend.is_live,
                      backend.model, plan, rounds)
    system = prompt.system_prompt()
    usage = res.usage

    try:
        parsed = await _ask(
            backend, usage, plan,
            AuthorRequest("draft", bt, system, prompt.draft_prompt(bt)),
            personas_required=True,
        )
    except (prompt.ReplyParseError, BudgetExceeded) as e:
        res.unreadable = True
        res.notes.append(f"The model's first reply could not be read, even after one retry: {e}")
        res.log.append(RoundLog(0, "draft", note="unreadable reply"))
        _write(res)
        return res
    res.playbook_text, res.personas_text = parsed.playbook, parsed.personas or ""
    res.log.append(RoundLog(0, "draft", note=f"first draft by {backend.name}"))
    say(f"draft written by {backend.name}")

    with tempfile.TemporaryDirectory(prefix=".stage-", dir=out_dir) as stage:
        for n in range(rounds + 1):
            problems, pb, pf = check_draft(business_type, res.playbook_text, res.personas_text)
            res.problems, res.pb, res.pf = problems, pb, pf
            res.report, res.failures = None, []
            action: str | None = None
            found: list[str] = []
            if problems:
                found = problems
                say(f"round {n}: {len(problems)} validator problem(s)")
                action = "repair"
                prompt_text = prompt.repair_prompt(problems, res.playbook_text, res.personas_text)
            else:
                report = await run_dryrun_on_texts(
                    business_type, res.playbook_text, res.personas_text, Path(stage)
                )
                res.report = report
                res.failures = collect_failures(report)
                res.safety_seen |= {p for p, _s in report.safety_violations}
                missing = sorted(res.safety_seen - {p.id for p in (pf.personas if pf else [])})
                res.safety_waived = missing
                found = [f.text().splitlines()[0] for f in res.failures]
                say(f"round {n}: dry run {report.total:.0%}, {len(res.failures)} persona(s) "
                    f"failing, {len(report.safety_violations)} safety violation(s)")
                if not res.failures and not missing:
                    break
                action = "patch"
                to_fix = [f.text() for f in res.failures]
                if missing:
                    to_fix.append(
                        "Personas that had safety violations were REMOVED: " + ", ".join(missing)
                        + ". Put them back; a safety problem cannot be waived by deleting its test."
                    )
                prompt_text = prompt.patch_prompt(to_fix, res.playbook_text, res.personas_text)
            if n == rounds:
                res.notes.append(
                    f"Stopped after {rounds} improvement round(s); problems remain (see below)."
                )
                break
            before_exp = _expectations(pf)
            try:
                parsed = await _ask(
                    backend, usage, plan,
                    AuthorRequest(action, bt, system, prompt_text,  # type: ignore[arg-type]
                                  previous_playbook=res.playbook_text,
                                  previous_personas=res.personas_text),
                    personas_required=False,
                )
            except (prompt.ReplyParseError, BudgetExceeded) as e:
                res.notes.append(f"Stopped: {e}")
                break
            res.log.append(RoundLog(n + 1, action, found, f"{action} applied"))
            res.playbook_text = parsed.playbook
            if parsed.personas:
                res.personas_text = parsed.personas
            if action == "patch":
                try:
                    after = _expectations(_load_personas_text(res.personas_text))
                except (yaml.YAMLError, ValidationError, ValueError):
                    after = {}
                for pid, old in before_exp.items():
                    if pid not in after:
                        if after:
                            res.removed_personas.append(pid)
                    elif after[pid] != old:
                        res.expect_changes.append(
                            f"{pid}: expected {old or '-'} -> {after[pid] or '-'}"
                        )
    _finish(res)
    _write(res)
    return res


def _finish(res: DraftResult) -> None:
    # a persona removed while its safety result was ever bad is a waiver attempt
    if res.pf is not None:
        ids = {p.id for p in res.pf.personas}
        res.safety_waived = sorted(res.safety_seen - ids)


def draft_sync(*args: Any, **kw: Any) -> DraftResult:
    return asyncio.run(run_draft(*args, **kw))


# =============================================================================== writing
def _write(res: DraftResult) -> None:
    from friday.playbooks.authoring.report import render_report

    d = res.out_dir
    d.mkdir(parents=True, exist_ok=True)
    if res.playbook_text:
        (d / "playbook.yaml").write_text(res.playbook_text, encoding="utf-8")
        res.files["playbook"] = d / "playbook.yaml"
    if res.personas_text:
        (d / "personas.yaml").write_text(res.personas_text, encoding="utf-8")
        res.files["personas"] = d / "personas.yaml"
    if res.report is not None:
        (d / "dryrun.txt").write_text(dryrun.render_table(res.report) + "\n", encoding="utf-8")
        res.files["dryrun"] = d / "dryrun.txt"
    (d / "report.md").write_text(render_report(res), encoding="utf-8")
    res.files["report"] = d / "report.md"
