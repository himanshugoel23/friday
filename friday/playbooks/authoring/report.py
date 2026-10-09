"""``report.md``: the plain-language summary of a draft for the founder."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from friday.playbooks import dryrun
from friday.playbooks.model import Playbook

if TYPE_CHECKING:
    from friday.playbooks.authoring.author import DraftResult

_RISKY = re.compile(
    r"\b(advance|booking amount|payment|rupaye|confirm\w*|approval|book\w*|fees?)\b", re.I
)
STATUS_TEXT = {
    "ready_for_review": "READY FOR YOUR REVIEW. It validates and every simulated business behaved "
                        "as expected, with no safety problem. It is still only a draft.",
    "needs_work": "NEEDS WORK. It validates and is safe, but some simulated businesses did not "
                  "behave as expected (details below). Edit the draft or run it again.",
    "blocked_safety": "BLOCKED: SAFETY. At least one safety violation was found. This draft can "
                      "NEVER be promoted until it is fixed.",
    "failed": "FAILED. The draft does not validate (or could not be read). It cannot be promoted.",
}


def _flag(pb: Playbook, lid: str) -> list[str]:
    text = pb.text(lid)
    why = []
    if lid == pb.disclosure:
        why.append("AI disclosure (spoken first)")
    if pb.line_def(lid).commit:
        why.append("COMMIT line: the only line that books")
    if _RISKY.search(text):
        why.append("money / booking / confirmation wording")
    if len(text) > 140:
        why.append("long (over 140 characters)")
    return why


def _step_summary(pb: Playbook) -> list[str]:
    out = []
    for sid, st in pb.steps.items():
        ref = st.ask[-1] if st.ask else None
        lid = ref if isinstance(ref, str) else (ref.line if ref else None)
        asks = f"asks: \"{pb.text(lid)}\"" if lid and lid in pb.lines else (
            "closes the call" if st.final else "waits for the answer")
        n = sum(len(pb.actions(a)) for a in st.branches.values())
        out.append(f"* `{sid}` {asks} ({len(st.branches)} reactions, {n} actions)")
    return out


def render_report(res: DraftResult) -> str:
    L: list[str] = []
    a = L.append
    a(f"# Draft playbook: {res.title} (`{res.business_type}`)")
    a("")
    a(f"**Status: {STATUS_TEXT[res.status]}**")
    a("")
    a("## In plain words")
    a("")
    a(f"* Written by: {res.backend}.")
    kind = "a real model, once, offline" if res.live else "a fixed template (no AI model)"
    a(f"* How: {kind}. Friday's words on a live call are never written by a model: only the "
      "lines in this file are spoken.")
    u = res.usage
    if res.live:
        a(f"* Model calls: {u.calls} (limit {res.plan.max_calls}); tokens in {u.input_tokens}, "
          f"out {u.output_tokens}; estimated cost about Rs {u.cost_inr:.0f} (an estimate, not a "
          f"bill). Worst case allowed: Rs {res.plan.worst_case_cost_inr:.0f}.")
    else:
        a("* Cost: nothing (no model, no network).")
    done = max((r.number for r in res.log), default=0)
    a(f"* Improvement rounds used: {done} of {res.rounds_allowed} allowed.")
    pb = res.pb
    if pb is not None:
        branches = sum(len(s.branches) for s in pb.steps.values())
        a(f"* The call has {len(pb.steps)} steps, {branches} reactions to what the other side "
          f"says, {len(pb.lines)} lines Friday can speak and {len(pb.outcomes)} possible "
          f"endings ({', '.join(pb.outcomes)}).")
        a("")
        a("### The steps")
        a("")
        L.extend(_step_summary(pb))
    a("")
    a("## What the simulated businesses did")
    a("")
    if res.report is not None:
        runs = res.report.runs
        ok = sum(1 for r in runs if not r.failed)
        a(f"{ok} of {len(runs)} simulated businesses passed every check "
          f"(overall {res.report.total:.0%}). Full table: `dryrun.txt`.")
        a("")
        a("```")
        a(dryrun.render_table(res.report))
        a("```")
    else:
        a("The dry run did not happen because the draft does not validate.")
    a("")
    a("## What failed and what was fixed")
    a("")
    steps = [r for r in res.log if r.number > 0]
    if not steps:
        a("Nothing needed fixing: the first draft validated and passed the dry run."
          if res.passes else "No fixing round was run.")
    for r in steps:
        what = "validator errors" if r.action == "repair" else "weak spots from the dry run"
        a(f"* Round {r.number}: the model was asked to fix {what}:")
        for f in r.found[:12]:
            a(f"    * {f}")
        if len(r.found) > 12:
            a(f"    * ... and {len(r.found) - 12} more")
    for n in res.notes:
        a(f"* {n}")
    a("")
    if res.problems:
        a("### Still invalid")
        a("")
        for p in res.problems[:40]:
            a(f"* {p}")
        a("")
    if res.failures:
        a("### Still failing")
        a("")
        for f in res.failures:
            a(f"* `{f.persona}` ({f.title}): " + "; ".join(d for d in f.details if d))
        a("")
    a("## Safety result")
    a("")
    if res.report is None and not res.safety_waived:
        a("Not checked: the draft does not validate.")
    elif res.safety_violations or res.safety_waived:
        a("**SAFETY VIOLATIONS FOUND. This draft cannot be promoted.** Safety problems are never "
          "waived.")
        for p, s in res.safety_violations:
            a(f"* `{p}`: {s}")
        for p in res.safety_waived:
            a(f"* `{p}` had a safety problem and was then removed from the test set. That counts "
              "as a violation.")
    else:
        a("No safety violation: AI disclosure first, only scripted words, no secret words, no "
          "booking claim without delegation, stop requests honoured (checked independently of the "
          "script engine).")
    a("")
    if res.expect_changes or res.removed_personas:
        a("## Test changes the model made (check these)")
        a("")
        for c in res.expect_changes:
            a(f"* Expectation changed: {c}")
        for p in res.removed_personas:
            a(f"* Simulated business removed: `{p}`")
        a("")
    a("## Lines needing human review")
    a("")
    if pb is None:
        a("Not available: the draft does not validate.")
    else:
        a(f"Every one of the {len(pb.lines)} lines is new and must be read by a person before "
          "promotion. The flagged ones matter most. Listen to a line in Friday's voice with "
          "`uv run friday say \"<line text>\"`.")
        a("")
        a("| line id | text | why look closely |")
        a("|---|---|---|")
        order = sorted(pb.lines, key=lambda lid: (not _flag(pb, lid), lid))
        for lid in order:
            text = pb.text(lid).replace("|", "/")
            a(f"| `{lid}` | {text} | {'; '.join(_flag(pb, lid)) or '-'} |")
    a("")
    a("## What to do next")
    a("")
    a("1. Read `playbook.yaml` in this folder, especially the flagged lines above. Edit freely; "
      "then run `uv run friday playbook validate <path to playbook.yaml>`.")
    a("2. Listen to the important lines: "
      "`uv run friday say \"<line text>\" --out var/preview/x.wav`.")
    a("3. Read `dryrun.txt` (the table). To read a whole simulated conversation, promote the "
      "draft and use `uv run friday playbook dry-run <type> --show <persona id>`.")
    a(f"4. When you are happy, run `uv run friday playbook promote {res.business_type}`. It "
      "checks everything again and asks you to type the business type name. Nothing is ever "
      "promoted automatically.")
    return "\n".join(L) + "\n"
