"""Run the parity scenarios through the REAL inbound pipeline (in-process, simulator only).

Driver: the Chat Lab world (``friday.lab.world.LabWorld``): the same ``Runtime.handle`` path as the
web chat, over the in-memory channel, fake clock and fake providers. Each scenario gets a fresh
world with an invented saved tester, so nothing leaks between scenarios and nothing real is
reachable. Reports hold reply text of the invented tester only.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.bench import rules as R
from friday.bench.scenarios import Scenario

PASS, FAIL, NEEDS = "PASS", "FAIL", "NEEDS-CONNECTOR"
DEFAULT_DIR = Path("var/bench")
# Switches the web test turns on (deploy/enable-web-test.sh); the bench mirrors the live web chat.
FEATURE_SWITCHES = (
    "approach_planner_enabled", "shopping_assistant_enabled", "query_understanding_enabled",
    "agent_team_enabled", "proactive_intents_enabled", "style_layer_enabled", "parity_inr_only", "parity_ride_links",
    "parity_invites", "parity_status", "guardrails_new_categories",
)
TESTERS = {"hinglish": "+919800000001", "english": "+919800000002"}  # invented lab users


@dataclass
class Result:
    id: str
    category: str
    capability: str
    expected_today: str
    status: str
    messages: list[str]
    reply: str
    buttons: list[str]
    failed: list[dict[str, str]] = field(default_factory=list)
    error: str = ""
    judge: str = ""
    llm: str = "fake"

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def evaluate(sc: Scenario, reply: R.Reply) -> list[dict[str, str]]:
    ctx = R.Ctx(user_text=sc.messages[-1])
    failed = []
    for name, arg in sc.rules:
        ok, detail = R.check(name, reply, ctx, arg)
        if not ok:
            failed.append({"rule": name, "detail": detail})
    return failed


def classify(sc: Scenario, reply: R.Reply, failed: list[dict[str, str]]) -> str:
    if not failed:
        return PASS
    if sc.expected_today == "needs connector":
        ctx = R.Ctx(user_text=sc.messages[-1])
        if all(R.check(n, reply, ctx)[0] for n in R.HONEST_RULES):
            return NEEDS  # honest about what it needs; the connector is the gap
    return FAIL


def _features(fake: bool) -> dict[str, bool]:
    from friday.core.config import Settings

    return {k: True for k in FEATURE_SWITCHES if k in Settings.model_fields}


_JUDGE_SYSTEM = (
    "You grade a personal-assistant chat reply for an Indian user. Answer in ONE line: "
    "'GOOD' or 'WEAK' then a reason of at most 20 words. Good = honest about what it can do, "
    "useful next step, no invented facts or prices, same script as the user."
)


async def _judge(llm: Any, sc: Scenario, reply: R.Reply) -> str:
    """Optional LLM verdict (--judge, real key only). Never decides PASS/FAIL; errors are swallowed."""
    from friday.core.interfaces import LLMMessage

    try:
        prompt = f"User: {' / '.join(sc.messages)}\nReply: {reply.text}"
        out = await llm.complete(
            system=_JUDGE_SYSTEM, messages=[LLMMessage(role="user", content=prompt)], purpose="bench_judge", max_tokens=80
        )
        return out.text.strip().splitlines()[0][:200]
    except Exception as e:  # noqa: BLE001
        return f"judge unavailable ({type(e).__name__})"


async def run_one(sc: Scenario, *, fake: bool, judge: bool = False, env: Any = None, world_factory: Callable[..., Any] | None = None) -> Result:
    from friday.lab.world import LabWorld

    make = world_factory or LabWorld.create
    w = None
    reply = R.Reply()
    err = ""
    verdict = ""
    llm = "fake"
    try:
        w = await make(notes_path=DEFAULT_DIR / "notes.jsonl", overrides=_features(fake), **({"env": env} if env is not None else {}))
        if not fake and w.real_llm_available():
            w.set_llm("real")
            llm = "real"
        phone = TESTERS[sc.user]
        for m in sc.messages:
            turn = await w.send_inbound(phone, w.inbound_text(phone, m), m)
            outs = turn.get("outputs") or []
            reply = R.Reply([o["text"] or "" for o in outs], [b for o in outs for b in o["buttons"]])
        if judge and not fake and w.llm_mode == "real":
            verdict = await _judge(w.runtime.pipeline.brain().llm, sc, reply)
    except Exception as e:  # noqa: BLE001 - a crashing scenario is a FAIL, never aborts the run
        err = f"{type(e).__name__}: {e}"[:300]
    finally:
        if w is not None:
            await w.close()
    failed = evaluate(sc, reply)
    if err:
        failed.insert(0, {"rule": "pipeline_error", "detail": err})
    status = classify(sc, reply, failed) if not err else FAIL
    res = Result(
        id=sc.id, category=sc.category, capability=sc.capability, expected_today=sc.expected_today,
        status=status, messages=list(sc.messages), reply=reply.text, buttons=reply.buttons, failed=failed, error=err,
        judge=verdict, llm=llm,
    )
    return res


async def run(scenarios: list[Scenario], *, fake: bool, judge: bool = False, env: Any = None, world_factory: Callable[..., Any] | None = None) -> dict[str, Any]:
    started = time.time()
    results = [await run_one(s, fake=fake, judge=judge, env=env, world_factory=world_factory) for s in scenarios]
    modes = {r.llm for r in results}
    mode = "fake" if fake else ("real LLM" if modes == {"real"} else "fake LLM (no key found)" if modes == {"fake"} else "mixed")
    return build_report(results, mode=mode, seconds=time.time() - started)


def build_report(results: list[Result], *, mode: str, seconds: float = 0.0) -> dict[str, Any]:
    by_cat: dict[str, Counter] = {}
    rules_failed: Counter = Counter()
    for r in results:
        c = by_cat.setdefault(r.category, Counter())
        c["total"] += 1
        c[r.status] += 1
        for f in r.failed:
            rules_failed[f["rule"]] += 1
    tally = Counter(r.status for r in results)
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": mode,
        "seconds": round(seconds, 1),
        "scoreboard": {
            "total": len(results), "pass": tally[PASS], "fail": tally[FAIL], "needs_connector": tally[NEEDS],
            "by_category": {k: dict(v) for k, v in sorted(by_cat.items())},
            "top_failing_rules": rules_failed.most_common(5),
        },
        "results": [r.as_dict() for r in results],
    }


def render(report: dict[str, Any]) -> str:
    sb = report["scoreboard"]
    lines = [
        "FRIDAY INSTINCT-PARITY BENCHMARK",
        f"run: {report['generated_at']}  mode: {report['mode']}  ({report['seconds']} s)",
        "",
        f"TOTAL {sb['total']}   PASS {sb['pass']}   FAIL {sb['fail']}   NEEDS-CONNECTOR {sb['needs_connector']}",
        "",
        "By category (pass/total, fail, needs-connector):",
    ]
    for cat, c in sb["by_category"].items():
        lines.append(f"  {cat:<12} {c.get('PASS', 0)}/{c['total']}  fail {c.get('FAIL', 0)}  needs {c.get('NEEDS-CONNECTOR', 0)}")
    lines.append("")
    lines.append("Most common failing rules:")
    if sb["top_failing_rules"]:
        lines += [f"  {n:<28} {k}x" for n, k in sb["top_failing_rules"]]
    else:
        lines.append("  none")
    lines += ["", "=" * 60]
    for r in report["results"]:
        lines.append(f"[{r['status']}] {r['id']}  ({r['category']}/{r['capability']}, expected today: {r['expected_today']})")
        lines.append("  user:  " + " | ".join(r["messages"]))
        reply = r["reply"].replace("\n", "\n         ") or "(no reply)"
        lines.append("  reply: " + reply)
        if r["buttons"]:
            lines.append("  buttons: " + ", ".join(r["buttons"]))
        for f in r["failed"]:
            lines.append(f"  FAILED RULE {f['rule']}: {f['detail']}")
        if r.get("judge"):
            lines.append("  judge: " + r["judge"])
        lines.append("")
    return "\n".join(lines)


def write(report: dict[str, Any], out_dir: Path | str | None = None) -> tuple[Path, Path]:
    d = Path(out_dir) if out_dir else DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    js, txt = d / "last.json", d / "last.txt"
    js.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    txt.write_text(render(report), encoding="utf-8")
    return js, txt
