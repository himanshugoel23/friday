"""``friday review`` and ``friday eval`` (wired from friday/cli.py with two small hooks).

    friday review                      list recent stored calls (id, when, labels, rating)
    friday review show CALL_ID         the redacted transcript
    friday review label CALL_ID robotic too_long --note "sounded like a script"
    friday review label CALL_ID robotic --remove
    friday review rate CALL_ID 4       record a post-call rating (1-5, up, down)
    friday review purge                delete transcripts past their retention window

    friday eval                        run the scripted scenarios, compare with the baseline
    friday eval --update-baseline      accept the current results as the new baseline
    friday eval --from-labelled        also turn labelled real calls into scenarios
    friday eval --live [--judge]       real LLM key from the environment (costs money)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from friday.quality.labels import LABELS

DEFAULT_LABELLED_DIR = Path("var/quality/labelled")


def register(sub: Any) -> None:
    review = sub.add_parser("review", help="quality loop: list, read and label stored calls")
    rsub = review.add_subparsers(dest="review_cmd")
    lst = rsub.add_parser("list", help="recent stored calls (default)")
    lst.add_argument("--limit", type=int, default=20)
    lst.add_argument("--unlabelled", action="store_true")
    show = rsub.add_parser("show", help="print one redacted transcript")
    show.add_argument("call_id")
    label = rsub.add_parser("label", help=f"attach labels: {', '.join(LABELS)}")
    label.add_argument("call_id")
    label.add_argument("labels", nargs="*")
    label.add_argument("--note", default=None, help="free-text note")
    label.add_argument("--remove", action="store_true", help="take these labels off")
    rate = rsub.add_parser("rate", help="record a post-call rating")
    rate.add_argument("call_id")
    rate.add_argument("rating", help="1-5, up or down")
    rsub.add_parser("purge", help="delete transcripts past the retention window")
    review.add_argument("--limit", type=int, default=20)  # `friday review --limit 5`

    ev = sub.add_parser("eval", help="quality loop: scripted caller scenarios, scored")
    ev.add_argument("--live", action="store_true", help="real LLM key from the environment")
    ev.add_argument("--judge", action="store_true", help="with --live: LLM-judge rubric scores")
    ev.add_argument("--update-baseline", action="store_true")
    ev.add_argument("--baseline", default=None, help="baseline file (default: the shipped one)")
    ev.add_argument("--strict", action="store_true", help="fail on ANY failing check")
    ev.add_argument("--only", default=None, help="run scenarios whose id contains this text")
    ev.add_argument("--from-labelled", action="store_true",
                    help="export labelled real calls as scenarios and include them")
    ev.add_argument("--labelled-dir", default=str(DEFAULT_LABELLED_DIR))
    ev.add_argument("--json", action="store_true")


def run_eval_command(args: argparse.Namespace, settings_factory: Any) -> int:
    from friday.quality import evalrun
    from friday.quality.harness import eval_settings
    from friday.quality.scenarios import SCENARIO_DIR, load_scenarios

    labelled_dir = Path(args.labelled_dir)
    if args.from_labelled:
        try:
            n = asyncio.run(export_labelled(settings_factory(), labelled_dir))
        except Exception as e:  # noqa: BLE001
            print(f"Could not read labelled calls: {type(e).__name__}")
            return 2
        print(f"Exported {n} labelled call(s) as scenarios into {labelled_dir}")
    dirs = [SCENARIO_DIR] + ([labelled_dir] if labelled_dir.exists() else [])
    scenarios = load_scenarios(*dirs)
    if args.only:
        scenarios = [s for s in scenarios if args.only in s.id]
    if not scenarios:
        print("No scenarios found.")
        return 2
    judge_llm: Any = None
    if args.live:
        settings = eval_settings(live=True)
        if not settings.llm_key_configured() or settings.resolve_llm() == "fake":
            print("--live needs an LLM key in the environment (no key found). Not running.")
            return 2
        if args.judge:
            from friday.core.container import Container

            judge_llm = Container(settings).get("llm")
        print(f"LIVE: scenarios use the real model ({settings.resolve_llm()}). This costs money.")
    elif args.judge:
        print("--judge needs --live (it asks a real model). Not running.")
        return 2
    path = Path(args.baseline) if args.baseline else evalrun.BASELINE_PATH
    baseline = evalrun.load_baseline(path)
    report = asyncio.run(evalrun.run_eval(scenarios, live=args.live, judge_llm=judge_llm))
    if args.json:
        print(json.dumps(report.as_baseline(), indent=2))
    else:
        print(evalrun.render_table(report, baseline))
    if args.update_baseline:
        evalrun.save_baseline(report, path)
        print(f"\nBaseline saved to {path}")
        return 0
    problems = evalrun.find_regressions(report, baseline)
    if baseline is None:
        print("\nNo baseline yet. Run `friday eval --update-baseline` to save one.")
    if problems:
        print("\nREGRESSION vs baseline:")
        for p in problems:
            print(f"  - {p}")
        return 1
    if args.strict and any(s.failed for s in report.scores):
        print("\n--strict: some checks fail.")
        return 1
    print("\nNo regression vs baseline." if baseline else "")
    return 0


async def export_labelled(settings: Any, out_dir: Path) -> int:
    from friday.core.container import Container
    from friday.quality.evalrun import scenario_from_stored
    from friday.quality.store import TranscriptStore

    c = Container(settings)
    try:
        calls = await TranscriptStore.from_container(c).recent(500, labelled=True)
    finally:
        await c.aclose()
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    for call in calls:
        sc = scenario_from_stored(call)
        (out_dir / f"{sc.id}.json").write_text(
            json.dumps(sc.to_json(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return len(calls)


# ------------------------------------------------------------------ review
def run_review_command(args: argparse.Namespace, settings: Any) -> int:
    return asyncio.run(_review(args, settings))


async def _review(args: argparse.Namespace, settings: Any) -> int:
    from friday.core.container import Container
    from friday.quality.store import TranscriptStore

    c = Container(settings)
    try:
        store = TranscriptStore.from_container(c)
        cmd = args.review_cmd or "list"
        if cmd == "list":
            limit = getattr(args, "limit", 20)
            only_new = False if getattr(args, "unlabelled", False) else None
            calls = await store.recent(limit, labelled=only_new)
            if not calls:
                print("No stored calls yet (only callers who agreed to storage are kept).")
            for x in calls:
                rating = x.rating if x.rating is not None else "-"
                outcome = str(x.meta.get("outcome", ""))
                print(f"{x.call_id}  {x.stored_at:%Y-%m-%d %H:%M}  {outcome:10} "
                      f"{x.meta.get('duration_s', 0):>5.0f}s  rating {rating}  "
                      f"[{', '.join(x.labels) or 'unlabelled'}]")
            return 0
        if cmd == "show":
            call = await store.get(args.call_id)
            if call is None:
                print("No stored call with that id.")
                return 1
            print(f"{call.call_id}  labels: {', '.join(call.labels) or '-'}  rating: {call.rating}")
            if call.note:
                print(f"note: {call.note}")
            for t in call.transcript:
                print(f"  {t['speaker']:>6}: {t['text']}")
            return 0
        if cmd == "label":
            if not args.labels and args.note is None:
                print(f"Give at least one label ({', '.join(LABELS)}) or --note.")
                return 2
            try:
                ok = await store.add_labels(
                    args.call_id, args.labels, note=args.note, remove=args.remove
                )
            except ValueError as e:
                print(e)
                return 2
            print("Saved." if ok else "No stored call with that id.")
            return 0 if ok else 1
        if cmd == "rate":
            try:
                ok = await store.record_rating(args.call_id, args.rating)
            except ValueError as e:
                print(e)
                return 2
            print("Saved." if ok else "No stored call with that id.")
            return 0 if ok else 1
        if cmd == "purge":
            print(f"Deleted {await store.purge_expired()} expired transcript(s).")
            return 0
        return 2
    finally:
        await c.aclose()
