"""`friday connectors list | demo-pizza --fake` (wired from friday/cli.py). Localhost only."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import socket
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from friday.connectors.defaults import build_default_registry
from friday.connectors.fake_site import FakeSiteServer, FakeSiteState, SimBrowserSession
from friday.connectors.food.zomato import ZomatoFoodConnector
from friday.connectors.gate import ActionGate, Grant
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.pizza_flow import FlowResult, Proposal, WantedItem, run_pizza_flow
from friday.connectors.recorder import RecordingSession, StepRecorder
from friday.connectors.registry import BackendKind, ConnectorRegistry, Registration, Status
from friday.connectors.report import render_report
from friday.connectors.scrub import scrub
from friday.connectors.watch import WatchRegistry

DEMO_PHONE = "9000000001"  # invented; the fake site accepts any number
DEMO_OTP = "246810"  # the fake site's fixed code (a test value, not a secret)


def register(sub: Any) -> None:
    cn = sub.add_parser("connectors", help="browser connectors: list, demo-pizza --fake")
    csub = cn.add_subparsers(dest="connectors_cmd")
    csub.add_parser("list", help="registered connectors, backends and status")
    d = csub.add_parser("demo-pizza", help="order a pizza on the FAKE site, stopping at the QR")
    d.add_argument("--fake", action="store_true", help="required: only the fake site is allowed")
    d.add_argument("--engine", choices=["playwright", "sim"], default="playwright",
                   help="playwright = real Chromium on the fake site (default); sim = in-process")
    d.add_argument("--watch", action="store_true", help="serve the live watch page on localhost")
    d.add_argument("--out", default=None, metavar="DIR", help="write DIR/report.html")
    d.add_argument("--hold", type=float, default=None,
                   help="with --watch: keep serving this many seconds (default: until Ctrl-C)")


def run_command(args: argparse.Namespace) -> int:
    if args.connectors_cmd == "list":
        for row in build_default_registry().describe():
            print("  ".join(f"{k}={v}" for k, v in row.items() if v))
        return 0
    if args.connectors_cmd == "demo-pizza":
        if not args.fake:
            print("REFUSED: only --fake is supported (the real site is unverified, no network).")
            return 2
        return asyncio.run(_demo(args))
    print("usage: friday connectors list | demo-pizza --fake [--watch] [--out DIR]")
    return 2


async def run_demo_flow(
    engine: str, recorder: StepRecorder, trace_to: str | None = None
) -> FlowResult:
    """Fake site + chosen engine + the full pizza flow. Used by the CLI and by tests."""
    state = FakeSiteState(otp=DEMO_OTP)
    otp = OneTimeOtpChannel()
    server = FakeSiteServer(state)
    session: Any
    base = server.start() if engine == "playwright" else "http://fake.invalid"
    try:
        if engine == "playwright":
            from friday.connectors.browser.playwright_session import PlaywrightBrowserSession

            session = await PlaywrightBrowserSession.open(
                allowed_hosts={"127.0.0.1"}, trace=trace_to is not None)
        else:
            session = SimBrowserSession(state)
        raw = session
        rec_session = RecordingSession(session, recorder)
        connector = ZomatoFoodConnector(
            rec_session, base_url=base, task_id="demo-task", otp_channel=otp,
            phone=DEMO_PHONE, otp_wait_s=10, poll_s=0.05)
        reg = ConnectorRegistry()
        reg.register(Registration("zomato", "food", BackendKind.scripted_browser, Status.live,
                                  "demo", connector=connector, fallback_url=base))
        otp.submit("demo-task", DEMO_OTP)  # stands in for the user typing it on the secure page

        async def approve(p: Proposal) -> Grant:
            return Grant(
                task_id=p.task_id, connector=p.connector, restaurant_id=p.restaurant_id,
                items=p.items, max_total_paise=int(p.estimated_subtotal_paise * 1.5),
                expires_at=datetime.now(UTC) + timedelta(minutes=10))

        result = await run_pizza_flow(
            reg, ActionGate(), task_id="demo-task", area="Sector 12",
            wanted=[WantedItem("margherita", 2), WantedItem("garlic")], approve=approve,
            recorder=recorder)
        if trace_to:
            await raw.stop_trace(trace_to)
        await raw.close()
        return result
    finally:
        server.stop()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_report(out: Path, html: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(html)


async def _demo(args: argparse.Namespace) -> int:
    recorder = StepRecorder()
    trace_path = str(Path(tempfile.mkdtemp(prefix="friday-trace-")) / "trace.zip") \
        if args.watch and args.engine == "playwright" else None
    watcher: threading.Thread | None = None
    if args.watch:
        import uvicorn
        from fastapi import FastAPI

        from friday.api.connectors_watch import watch_router

        registry = WatchRegistry()
        entry_token = registry.create("demo-task", recorder, ttl_seconds=3600)
        registry.get(entry_token).trace_path = trace_path  # type: ignore[union-attr]
        app = FastAPI()
        app.include_router(watch_router(registry), prefix="/connectors")
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                               log_level="warning"))
        watcher = threading.Thread(target=server.run, daemon=True)
        watcher.start()
        await asyncio.sleep(0.5)
        print(f"WATCH: http://127.0.0.1:{port}/connectors/watch/{entry_token}")
    result = await run_demo_flow(args.engine, recorder, trace_path)
    print(json.dumps(scrub(result.model_dump()), indent=2, default=str))
    if args.out:
        out = Path(args.out)
        html = render_report(recorder, "Friday demo: pizza (fake site)")
        await asyncio.to_thread(_write_report, out, html)
        print(f"REPORT: {out / 'report.html'}")
    if watcher is not None:
        with contextlib.suppress(KeyboardInterrupt, asyncio.CancelledError):
            await asyncio.sleep(args.hold if args.hold is not None else 10**9)
    return 0 if result.status == "payment_ready" else 1
