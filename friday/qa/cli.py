# ruff: noqa: E501
"""``friday qa``: manual QA of every built feature, with REAL calls to your OWN phone only.

    friday qa list                       the scenarios, real vs simulated parts
    friday qa show <id>                  what a scenario will do (nothing is dialled)
    friday qa run <id>                   run one scenario here (you type: YES, call my phone)
    friday qa serve                      the page for your iPad (port 8767, token link)
    friday qa report                     verdicts + the pending line ids you heard
    friday qa note <id> --verdict ok|wording|bug [--note "..."]
    friday qa line <line_id> approve|reject [--note "..."]

Needs FRIDAY_QA_LIVE=true, FRIDAY_MODE=live, FRIDAY_PROFILE=pilot and exactly your one number in
FRIDAY_PILOT_ALLOWED_NUMBERS (names only; docs/QA_MANUAL.md). Never reads or prints .env.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from friday.integration.telephony import scrub_text
from friday.qa import report as qa_report
from friday.qa import scenarios as sc
from friday.qa.config import APPROVAL_PHRASE, DEFAULT_PORT, QaConfig
from friday.qa.safety import QaGuard, QaRefused
from friday.qa.store import QaStore

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    p = sub.add_parser("qa", help="manual QA with real calls to your own phone (docs/QA_MANUAL.md)")
    q = p.add_subparsers(dest="qa_cmd", required=True)
    q.add_parser("list", help="the scenarios and what is real or simulated in each")
    show = q.add_parser("show", help="what a scenario will do; dials nothing")
    show.add_argument("scenario")
    run = q.add_parser("run", help="run one scenario (asks you to type the approval phrase)")
    run.add_argument("scenario")
    run.add_argument(
        "--vendor", default=None, help="business name to say (default: top of the shortlist)"
    )
    run.add_argument("--area", default=None)
    run.add_argument("--first-name", default=None)
    serve = q.add_parser("serve", help="the QA page for your iPad (token link; port 8767)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--public-url", default=None, help="https address you open from the iPad")
    serve.add_argument("--ttl-hours", type=float, default=8.0)
    q.add_parser("report", help="verdicts per scenario and the pending line ids you heard")
    note = q.add_parser("note", help="record a verdict / note for a scenario")
    note.add_argument("scenario")
    note.add_argument("--verdict", choices=["ok", "wording", "bug"], default="")
    note.add_argument("--note", default="")
    line = q.add_parser("line", help="approve or reject a pending line id you heard")
    line.add_argument("line_id")
    line.add_argument("decision", choices=["approve", "reject"])
    line.add_argument("--note", default="")
    ex = q.add_parser(
        "exec", help=argparse.SUPPRESS
    )  # used by the page: one call in its own process
    ex.add_argument("scenario")
    ex.add_argument("--run-id", required=True)
    ex.add_argument("--seconds", type=int, default=None)
    ex.add_argument("--first-name", default=sc.DEFAULT_FIRST_NAME)
    ex.add_argument("--vendor", default="")
    ex.add_argument("--area", default="")
    ex.add_argument("--approved", default="")


def qa_url(base: str, token: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/qa"):
        base = base[: -len("/qa")]
    return f"{base}/qa/{token}/"


def _print_plan(plan: dict[str, Any], out=print) -> None:  # noqa: ANN001
    out(f"\n== {plan['title']}  [{plan['kind']}] ==")
    out(plan["summary"])
    out("\nWhat will happen:")
    for i, step in enumerate(plan["steps"], 1):
        out(f"  {i}. {step}")
    if plan["kind"] == sc.KIND_CALL:
        out(
            f"\nCalls: {plan['number']} (your allow-listed phone, last 2 digits shown), at most {plan['seconds']} s, estimated cost up to Rs {plan['est_cost_inr']}"
        )
        if plan.get("shortlist"):
            sl = plan["shortlist"]
            out(
                f"\nShortlist ({sl['source']}; names only, NOT dialled, your phone is called instead):"
            )
            for it in sl["items"]:
                rating = f", rating {it['rating']}" if it.get("rating") else ""
                out(f"  - {it['name']}{rating}")
            if sl.get("note"):
                out(f"  ({sl['note']})")
            out(f"  The script will use the name: {plan['vendor']}")
        if plan.get("wait"):
            out(f"\n{plan['wait']}")
    out(f"\nYou should hear/see: {plan['hear']}")
    out("\nREAL:")
    for x in plan["real"]:
        out(f"  + {x}")
    out("SIMULATED:")
    for x in plan["simulated"]:
        out(f"  ~ {x}")


def _build(settings: Any, qa: QaConfig, store: QaStore, *, in_process: bool) -> Any:
    from friday.qa.live import LabChat, LiveBackend, SubprocessBackend
    from friday.qa.runner import QaRunner

    guard = QaGuard(settings, qa, store)
    backend = LiveBackend(settings, qa) if in_process else SubprocessBackend()
    return QaRunner(guard, store, backend, LabChat(qa.path / "lab_notes.jsonl"), qa=qa)


async def _run_one(args: argparse.Namespace, settings: Any, qa: QaConfig, store: QaStore) -> int:
    runner = _build(settings, qa, store, in_process=True)
    s = sc.get(args.scenario)
    try:
        runner.guard.require_startable()
        params = {
            k: v
            for k, v in (
                ("vendor", args.vendor),
                ("area", args.area),
                ("first_name", args.first_name),
            )
            if v
        }
        _print_plan(await runner.plan(s.id, params))
        approval = ""
        if s.needs_approval:
            approval = await asyncio.to_thread(
                input,
                f"\nType exactly  {APPROVAL_PHRASE}  to place the call (anything else cancels): ",
            )
        run = await runner.start(s.id, approval, params)
    except QaRefused as e:
        print(f"REFUSED: {e}")
        return 2
    except KeyError as e:
        print(f"REFUSED: {e}")
        return 2
    seen = 0
    last_tick = -1
    try:
        while run.phase not in ("done", "failed", "cancelled", "refused"):
            if run.phase == "countdown" and run.ring_at:
                left = max(0, int(run.ring_at - runner.clock()))
                if left != last_tick and (left % 5 == 0 or left <= 5):
                    print(f"   ring now in {left} s ... (Ctrl-C to cancel)")
                    last_tick = left
            while seen < len(run.lines):
                print("  " + run.lines[seen])
                seen += 1
            await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        runner.cancel(run.id)
        print("Cancelling...")
        await runner.wait(run.id)
    await runner.wait(run.id)
    for ln in run.lines[seen:]:
        print("  " + ln)
    rep = run.report
    print(f"\nResult: {run.phase}" + (f" ({run.error})" if run.error else ""))
    if rep:
        print(
            f"Status: {rep.status}, {rep.duration_s:.0f} s, estimated cost Rs {rep.cost_inr or run.est_cost_inr}"
        )
        for t in rep.transcript[:60]:
            print(f"  {t['who'].upper():>8}: {t['text']}")
    print(f'\nNow give your verdict:  friday qa note {s.id} --verdict ok|wording|bug --note "..."')
    return 0 if run.phase == "done" else 1


async def _exec(args: argparse.Namespace, settings: Any, qa: QaConfig, store: QaStore) -> int:
    """One real call in this process (started by the page). Prints `QA_REPORT {json}` at the end."""
    from friday.qa.live import REPORT_PREFIX, LiveBackend
    from friday.qa.models import CallReport, CallSpec

    def emit(line: str) -> None:
        print(scrub_text(line), flush=True)

    def finish(report: CallReport) -> None:
        print(REPORT_PREFIX + json.dumps(report.to_json()), flush=True)

    s = sc.get(args.scenario)
    guard = QaGuard(settings, qa, store)
    if args.approved != APPROVAL_PHRASE or s.kind != sc.KIND_CALL:
        emit("REFUSED: not approved")
        finish(CallReport(status="refused", summary="not approved"))
        return 2
    try:
        number, secs, _ = guard.check_call(guard.target, args.seconds)
    except QaRefused as e:
        emit(f"REFUSED: {e}")
        finish(CallReport(status="refused", summary=str(e)))
        return 2
    spec = CallSpec(
        scenario=s,
        number=number,
        seconds=secs,
        run_id=args.run_id,
        first_name=args.first_name,
        vendor_name=args.vendor,
        area=args.area,
    )
    try:
        with guard.session(s.id, args.run_id):
            report = await LiveBackend(settings, qa).run(spec, emit)
    except KeyboardInterrupt:
        report = CallReport(status="failed", summary="stopped by you (hang-up)")
    except Exception as e:  # noqa: BLE001
        emit(f"The call failed: {type(e).__name__}: {scrub_text(str(e))[:200]}")
        report = CallReport(status="failed", summary=type(e).__name__)
    finish(report)
    return 0


def run_command(args: argparse.Namespace) -> int:
    qa = QaConfig()
    store = QaStore(qa.path)
    cmd = args.qa_cmd
    if cmd == "list":
        for s in sc.SCENARIOS:
            real = (
                "REAL CALL"
                if s.kind == sc.KIND_CALL
                else ("simulator" if s.kind == sc.KIND_CHAT else "instructions")
            )
            print(f"{s.id:<26} [{real:<12}] {s.title}")
        return 0
    if cmd == "report":
        print(qa_report.render(store))
        return 0
    if cmd == "note":
        if args.scenario not in sc.BY_ID:
            print(f"REFUSED: no scenario named '{args.scenario}' (friday qa list)")
            return 2
        try:
            store.add_note(args.scenario, args.verdict, args.note)
        except ValueError as e:
            print(f"REFUSED: {e}")
            return 2
        print("Saved.")
        return 0
    if cmd == "line":
        store.add_line_decision(args.line_id, args.decision, args.note)
        print("Saved. (An approved id still needs the reviewed commit that flips its status.)")
        return 0
    from friday.core.config import Settings

    settings = Settings()
    if cmd == "show":
        runner = _build(settings, qa, store, in_process=True)
        try:
            _print_plan(asyncio.run(runner.plan(args.scenario)))
        except KeyError as e:
            print(f"REFUSED: {e}")
            return 2
        return 0
    if cmd == "exec":
        try:
            return asyncio.run(_exec(args, settings, qa, store))
        except KeyboardInterrupt:
            return 130
    if cmd == "run":
        try:
            return asyncio.run(_run_one(args, settings, qa, store))
        except KeyboardInterrupt:
            print("\nStopped by you.")
            return 130
    if cmd == "serve":
        return _serve(args, settings, qa, store)
    return 2


def _serve(args: argparse.Namespace, settings: Any, qa: QaConfig, store: QaStore) -> int:
    from friday.qa.app import create_qa_app

    try:
        app = create_qa_app(settings, qa, store=store, ttl_hours=args.ttl_hours)
    except QaRefused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    import uvicorn

    from friday.core.logging import setup_logging

    setup_logging("WARNING", False)
    guard: QaGuard = app.state.guard
    base = args.public_url or f"http://{args.host}:{args.port}"
    print("Friday QA: real calls to YOUR phone only.")
    print(
        f"Calls go to {guard.masked_target} (the one number on your allow-list). Nothing else is ever dialled."
    )
    print(
        f"Caps today: {qa.max_calls_per_day} calls, Rs {qa.max_spend_inr:g}, {guard.clamp_seconds()} s per call. Kill switch: friday pause."
    )
    print(
        f"\nOpen this link (secret; works for {args.ttl_hours:g} hours):\n\n  {qa_url(base, app.state.gate.token)}\n"
    )
    if args.host not in LOOPBACK:
        print(f"WARNING: listening on {args.host}; anyone who has the link can ring your phone.\n")
    sys.stdout.flush()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0
