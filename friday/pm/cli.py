"""CLI helpers: ``friday classify`` and ``friday pm-sim`` (offline unless a key is present)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .classifier import CHANNELS, KeywordClassifier, build_live_classifier
from .manager import ProjectManager
from .slots import GuardedRewriter  # noqa: F401  (re-exported for adapters)
from .state import MemoryTaskStore
from .steps import FakeStepAgents
from .taxonomy import DATA_DIR


def run_classify(args, settings) -> int:
    channel = getattr(args, "channel", "whatsapp_text")
    clf = build_live_classifier(settings)
    if clf is None:
        print("no OPENAI_API_KEY: using the offline keyword baseline (not the LLM)")
        clf = KeywordClassifier()
    else:
        print("using the live LLM classifier")
    c = asyncio.run(clf.classify(args.text, channel))
    print(json.dumps({**c.model_dump(), "channel": channel}, ensure_ascii=False))
    return 0


def load_scenario(name_or_path: str) -> dict:
    p = Path(name_or_path)
    if not p.exists():
        p = DATA_DIR / "scenarios" / f"{name_or_path}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def list_scenarios() -> list[str]:
    return sorted(p.stem for p in (DATA_DIR / "scenarios").glob("*.json"))


async def simulate(scn: dict, *, show_log: bool = False, out=print) -> str:
    """Run a transcript against fakes; returns the task id. Prints plan, questions, replies."""
    fake = scn.get("fake", {})
    agents = FakeStepAgents(fake.get("vendors"), pickup=fake.get("pickup"),
                            prices=fake.get("prices"))
    store = MemoryTaskStore()
    pm = ProjectManager(classifier=KeywordClassifier(), agents=agents, store=store,
                        id_factory=lambda: "sim")
    task_id = None
    default_channel = scn.get("channel", "whatsapp_text")
    for turn in scn["turns"]:
        text, channel = (turn, default_channel) if isinstance(turn, str) else (
            turn["user"], turn.get("channel", default_channel))
        r = await pm.handle_turn(task_id, text, channel, profile=scn.get("profile"),
                                 updates_on=scn.get("updates_on", False))
        task_id = r.task_id
        out(f"[{channel}] USER: {text}")
        out(f"[{channel}] FRIDAY: {r.reply_text or '(silence)'}   <{r.state}"
            f"{', waiting: ' + r.pending_kind if r.pending_kind else ''}>")
        for w in r.whatsapp:
            out(f"[whatsapp_text] FRIDAY: {w}")
        if r.background:
            bg = await pm.run_background(task_id)
            for m in bg.messages:
                out(f"[{bg.deliver_via}] FRIDAY: {m}")
            out(f"  (background run -> {bg.status})")
    task = store.load(task_id)
    out("\nPLAN (" + str(task.archetype) + f", radius {task.radius_km} km):")
    for s in task.plan:
        out(f"  {s.name:10s} {s.status}" + (f"  ({s.reason})" if s.reason else ""))
    out(f"slots: {task.slots}")
    out(f"status: {task.status.value}" + (f" ({task.stop_reason})" if task.stop_reason else ""))
    if show_log:
        out("\nDECISION LOG:")
        for d in task.log:
            out(f"  {d.kind}: {d.detail}")
    return task_id


def run_pm_sim(args) -> int:
    if args.list:
        print("\n".join(list_scenarios()))
        return 0
    scn = load_scenario(args.scenario)
    print(f"scenario: {args.scenario} - {scn.get('description', '')}\n")
    asyncio.run(simulate(scn, show_log=args.log))
    return 0


__all__ = ["CHANNELS", "run_classify", "run_pm_sim", "simulate"]
