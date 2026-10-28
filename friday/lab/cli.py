"""``friday lab``: start the Chat Lab (simulator only; never reads ``.env``; messages no one)."""

from __future__ import annotations

import argparse
import re
import sys

from friday.lab.app import DEFAULT_TTL_HOURS, create_lab_app
from friday.lab.safety import LabRefused, environment_settings

DEFAULT_PORT = 8766
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    p = sub.add_parser(
        "lab", help="Chat Lab: a WhatsApp-style test page for the chatbot (simulator only)"
    )
    p.add_argument("--host", default="127.0.0.1", help="bind address (default: this machine only)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument(
        "--public-url",
        default=None,
        help="the HTTPS address you open from your iPad, e.g. https://your-host "
        "(only changes the link printed below)",
    )
    p.add_argument(
        "--ttl-hours",
        type=float,
        default=DEFAULT_TTL_HOURS,
        help="the access token stops working after this many hours (default 8)",
    )
    p.add_argument(
        "--token",
        default=None,
        help="choose the link's secret yourself (16+ letters, digits, - or _) so it is easy to type on "
        "an iPad; default is a random one. The lab is a simulator, but pick something nobody can guess",
    )
    p.add_argument(
        "--notes",
        default="var/lab/notes.jsonl",
        help="where 'mark this reply wrong' notes are appended",
    )
    p.add_argument(
        "--allow-live-env",
        action="store_true",
        help="start even though FRIDAY_MODE=live is set in this environment; the lab "
        "still uses only the in-memory channel and fake numbers",
    )


def lab_url(base: str, token: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/lab"):
        base = base[: -len("/lab")]
    return f"{base}/lab/{token}/"


def run_command(args: argparse.Namespace) -> int:
    chosen = getattr(args, "token", None)
    if chosen is not None and not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", chosen):
        print("--token must be 16 to 64 characters: letters, digits, - or _")
        return 2
    try:
        env = environment_settings()
        app = create_lab_app(
            env=env,
            allow_live_env=args.allow_live_env,
            ttl_hours=args.ttl_hours,
            token=chosen,
            notes_path=args.notes,
        )
    except LabRefused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    import uvicorn

    from friday.core.logging import setup_logging

    setup_logging("WARNING", False)
    token = app.state.gate.token
    base = args.public_url or f"http://{args.host}:{args.port}"
    print("Friday Chat Lab: simulator only (fake WhatsApp, fake calls, fake clock).")
    print("It cannot message or call anyone. It does not read .env.")
    if env.is_live:
        print("NOTE: FRIDAY_MODE=live is set here; the lab ignores it and stays on the simulator.")
    link = lab_url(base, token)
    print(f"\nOpen this link (secret; works for {args.ttl_hours:g} hours):\n\n  {link}\n")
    if args.host not in LOOPBACK:
        print(f"WARNING: listening on {args.host}; anyone who has the link can use the lab.\n")
    sys.stdout.flush()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0
