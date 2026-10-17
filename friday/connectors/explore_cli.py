"""CLI for the founder-supervised Zomato explore run: `friday connectors zomato-explore | pack-run`.

The login phone comes from Settings.pilot_allowed_numbers (first entry) at RUNTIME; it is never
printed (only its last 2 digits), logged, written or committed. The login code comes only through
the one-time page (api/connectors_otp.py). The run stops before any order.
Runbook: docs/ZOMATO_EXPLORE.md.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import socket
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from friday.connectors.explore import ExploreConfig, local_digits, mask_phone, run_explore
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.otp_tokens import OtpTokenRegistry
from friday.connectors.pack import pack_run
from friday.connectors.recorder import StepRecorder
from friday.connectors.watch import WatchRegistry

TASK_ID = "zomato-explore"
DEFAULT_OUT_ROOT = "var/connectors/zomato-explore"
FAKE_PHONE = "9000000001"  # invented; the fake site accepts any number
FAKE_OTP = "246810"  # the fake site's fixed test code


def add_parsers(csub: Any) -> None:
    z = csub.add_parser("zomato-explore", help="founder-supervised REAL Zomato explore run "
                        "(login with your own number; stops before any order)")
    mode = z.add_mutually_exclusive_group()
    mode.add_argument("--headed", dest="headed", action="store_true", default=True,
                      help="visible Chromium (default; on a server run it under xvfb-run)")
    mode.add_argument("--headless", dest="headed", action="store_false", help="no visible window")
    z.add_argument("--area", default="Gurgaon", help="location to set / search in")
    z.add_argument("--query", default="Domino's", help="restaurant to search for")
    z.add_argument("--out", default=None, metavar="DIR",
                   help=f"run folder (default {DEFAULT_OUT_ROOT}/<timestamp>; var/ is gitignored)")
    z.add_argument("--watch-host", default="127.0.0.1",
                   help="bind address of the watch / code pages (use an SSH tunnel, or 0.0.0.0)")
    z.add_argument("--watch-port", type=int, default=8765)
    z.add_argument("--public-url", default=None, metavar="URL",
                   help="base URL the founder opens (default env FRIDAY_PUBLIC_URL, else "
                        "http://HOST:PORT)")
    z.add_argument("--hold", type=float, default=0.0, metavar="SECONDS",
                   help="keep the watch page up this long after the run (default 0)")
    z.add_argument("--add-item", default=None, metavar="NAME",
                   help="add this one dish, show the cart and the pay hand-off screen; "
                        "never pays or places an order")
    z.add_argument("--login-page", action="store_true",
                   help="open the site's /login page directly and test only the login (your number "
                        "and your own code; nothing else)")
    z.add_argument("--probe", action="store_true",
                   help="reachability check only: open the site, search, open the restaurant "
                        "and read the menu, then stop. No login, no phone number, no code")
    z.add_argument("--fake", action="store_true",
                   help="dry run against the local FAKE site (checks Chromium, xvfb and the pages)")
    p = csub.add_parser("pack-run", help="zip a run folder for the lead (no secrets)")
    p.add_argument("dir", metavar="DIR")
    p.add_argument("--zip", default=None, metavar="PATH", help="output zip (default DIR-pack.zip)")
    p.add_argument("--include-post-login-trace", action="store_true",
                   help="also include the after-login trace (holds session cookies: avoid)")


def _load_phone() -> str:
    from friday.core.config import get_settings

    nums = get_settings().pilot_allowed_numbers
    return str(nums[0]) if nums else ""


def _port_free(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def run_pack(args: argparse.Namespace) -> int:
    try:
        dest, included, skipped = pack_run(
            Path(args.dir), Path(args.zip) if args.zip else None, args.include_post_login_trace)
    except FileNotFoundError:
        print(f"Run folder not found: {args.dir}")
        return 2
    print(f"PACK: {dest}  ({len(included)} files, text scrubbed; {len(skipped)} files left out)")
    print("Send this zip. Do NOT paste the login code or your phone number anywhere.")
    return 0


def run_explore_command(args: argparse.Namespace) -> int:
    from friday.connectors.browser.playwright_session import find_chromium, playwright_installed

    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    if not playwright_installed() or find_chromium() is None:
        print("No browser available: install Playwright (uv sync --extra browser) and Chromium "
              "(set PLAYWRIGHT_CHROMIUM_PATH or run 'playwright install chromium'). "
              "deploy/zomato-explore.sh does this check for you.")
        return 2
    if args.headed and sys.platform.startswith("linux") and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("Headed mode needs a display. On the server use deploy/zomato-explore.sh "
              "(it runs under xvfb-run), or pass --headless.")
        return 2
    if args.probe and args.login_page:
        print("Use either --probe or --login-page, not both.")
        return 2
    if args.probe:
        phone = ""  # nothing is typed on the site in probe mode
    elif args.fake:
        phone = FAKE_PHONE
    else:
        try:
            phone = _load_phone()
        except Exception as e:  # noqa: BLE001 - never print the message: it could echo values
            print(f"Could not read settings ({type(e).__name__}).")
            return 2
        if not phone:
            print("No test phone number is configured. Set FRIDAY_PILOT_ALLOWED_NUMBERS on this "
                  "machine (the first number is used for the Zomato login). Nothing was run.")
            return 2
    if not args.probe and not local_digits(phone):
        print("The first allowed number is not a 10-digit Indian mobile number; the Zomato login "
              "step only supports +91 numbers. Nothing was run.")
        return 2
    if not _port_free(args.watch_host, args.watch_port):
        print(f"Port {args.watch_port} on {args.watch_host} is busy; pick another --watch-port.")
        return 2
    out = Path(args.out) if args.out else Path(DEFAULT_OUT_ROOT) / datetime.now(UTC).strftime(
        "%Y%m%d-%H%M%S")
    return asyncio.run(_run(args, phone, out))


async def _run(args: argparse.Namespace, phone: str, out: Path) -> int:
    import uvicorn
    from fastapi import FastAPI

    from friday.api.connectors_otp import otp_router
    from friday.api.connectors_watch import watch_router

    recorder, otp = StepRecorder(), OneTimeOtpChannel()
    watch, tokens = WatchRegistry(), OtpTokenRegistry()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(watch_router(watch), prefix="/connectors")
    app.include_router(otp_router(tokens, otp), prefix="/connectors")
    server = uvicorn.Server(uvicorn.Config(
        app, host=args.watch_host, port=args.watch_port, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    await asyncio.sleep(0.7)
    base = (args.public_url or os.environ.get("FRIDAY_PUBLIC_URL")
            or f"http://{args.watch_host}:{args.watch_port}").rstrip("/")
    watch_token = watch.create(TASK_ID, recorder, ttl_seconds=3 * 3600)
    if args.probe:
        print("PROBE: reachability check only (no login, no phone number, no code).")
    else:
        print(f"Using the first allowed test number (ending {mask_phone(phone)}).")
    print(f"WATCH PAGE: {base}/connectors/watch/{watch_token}")
    print("The one-time CODE PAGE link is printed when the site is ready for your code.")
    if args.watch_host not in {"127.0.0.1", "localhost"} and base.startswith("http://"):
        print("NOTE: plain http. Prefer an SSH tunnel or an https front for the code page.")

    def waiting() -> None:
        token = tokens.create(TASK_ID, phone[-2:])
        print(f"\nZomato should now text a login code to the number ending {mask_phone(phone)}.")
        print(f"CODE PAGE (valid 10 min, one use): {base}/connectors/otp/{token}")
        if args.fake:
            print(f"(fake site: the test code is {FAKE_OTP})")

    fake_srv = None
    base_url = "https://www.zomato.com"
    hosts = None
    if args.fake:
        from friday.connectors.fake_site import FakeSiteServer, FakeSiteState

        fake_srv = FakeSiteServer(FakeSiteState(otp=FAKE_OTP))
        base_url, hosts = fake_srv.start(), {"127.0.0.1"}
    cfg = ExploreConfig(
        out=out, base_url=base_url, area=args.area, query=args.query, headed=args.headed,
        add_item=args.add_item, probe=args.probe, login_page=args.login_page, phone=phone,
        otp=otp, task_id=TASK_ID, allowed_hosts=hosts, on_waiting_for_otp=waiting)
    print(f"Run folder: {out}")
    try:
        state = await run_explore(cfg, recorder)
        print(f"\nRESULT: {state['status']}")
        if state.get("blocked_reason"):
            print(f"REASON: {state['blocked_reason']['explanation']}")
        print(f"Next: uv run friday connectors pack-run {out}")
        if args.hold > 0:
            print(f"Holding the watch page for {args.hold:.0f}s (Ctrl-C to stop).")
            with contextlib.suppress(KeyboardInterrupt, asyncio.CancelledError):
                await asyncio.sleep(args.hold)
    finally:
        otp.wipe(TASK_ID)
        tokens.revoke_task(TASK_ID)
        watch.revoke_task(TASK_ID)
        server.should_exit = True
        thread.join(timeout=3)
        if fake_srv:
            fake_srv.stop()
    return 0 if state["status"] == "done" else 3
