# ruff: noqa: E501
"""Plan validation. Runs on EVERY plan (data or model) before the browser is touched, and again on a re-plan.

Rules: known step types only; at most 12 steps; starts with open_site and ends with report; no payment / sign /
account-creation wording in any title or argument; allowed domains are not government / identity / payment hosts.
Returns the list of problems (empty list = valid)."""

from __future__ import annotations

from friday.browser_agent import rules
from friday.steps import playbooks
from friday.steps.types import Step, StepPlan, StepType

MAX_STEPS = 12
KNOWN = frozenset(t.value for t in StepType)


def problems(plan: StepPlan) -> list[str]:
    out: list[str] = []
    steps = plan.steps
    if not steps:
        return ["empty plan"]
    if len(steps) > MAX_STEPS:
        out.append(f"too many steps ({len(steps)})")
    if steps[0].type != StepType.OPEN_SITE:
        out.append("the first step must be open_site")
    if steps[-1].type != StepType.REPORT:
        out.append("the last step must be report")
    if not plan.domains:
        out.append("no allowed site")
    for d in plan.domains:
        if rules.domain_denied(d):
            out.append(f"site {d} is never opened")
    bad = playbooks.forbidden_re()
    for i, s in enumerate(steps, 1):
        if s.type.value not in KNOWN:
            out.append(f"step {i}: unknown type")
        text = " ".join([s.title, *s.args.keys(), *s.args.values()])
        hit = bad.search(text)
        if hit:
            out.append(f"step {i}: '{hit.group(0)}' is a payment / signing / account step, which never exists")
        if s.type == StepType.ACT_CONFIRMED and i == 1:
            out.append("an irreversible step cannot come first")
    return out


def is_valid(plan: StepPlan) -> bool:
    return not problems(plan)


def parse_steps(raw: object) -> list[Step] | None:
    """Raw model output ({'steps': [{'type', 'title', 'args'}]}) -> Steps of the closed schema, or None if anything is off."""
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
        return None
    out: list[Step] = []
    for item in raw["steps"]:
        if not isinstance(item, dict) or item.get("type") not in KNOWN:
            return None
        args = item.get("args") or {}
        if not isinstance(args, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in args.items()):
            return None
        out.append(Step(type=StepType(item["type"]), title=str(item.get("title") or "")[:60], args={k[:30]: v[:160] for k, v in list(args.items())[:4]}))
    return out
