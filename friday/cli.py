"""`friday` command line.

    uv run friday check     # show mode + resolved providers + which modules exist
    uv run friday initdb    # create tables in FRIDAY_DATABASE_URL
    uv run friday serve     # run the API (needs friday.api.app:create_app)
    uv run friday worker --roles voice,task   # background roles without the HTTP server
    uv run friday chat      # local WhatsApp simulator chat (needs friday.channels.cli:main)

Owner: EM scaffold -> QA Engineer finalises the run commands.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import signal
import sys

from friday.core.config import Settings
from friday.core.container import FACTORIES, Container
from friday.core.logging import setup_logging


def _check(settings: Settings) -> int:
    c = Container(settings)
    print(f"mode: {settings.mode}   db: {settings.database_url.split('@')[-1]}")
    print(f"roles: {','.join(settings.roles)}")
    for component in FACTORIES:
        provider = c.provider_for(component)
        try:
            path = c.factory_path(component)
        except Exception as e:  # noqa: BLE001
            print(f"  {component:20s} {provider:14s} ERROR {e}")
            continue
        status = "ok" if c.is_available(component) else "not implemented yet"
        print(f"  {component:20s} {provider:14s} {path:60s} {status}")
    missing = c.missing_role_components()
    if missing:
        print(f"  ! components needed by roles {','.join(settings.roles)} but not implemented: "
              + ", ".join(missing))
    if not settings.is_live:
        return 0
    problems = settings.live_problems()
    if not problems:
        print("live configuration: OK")
        return 1 if missing else 0
    print(f"\nLIVE CONFIGURATION INCOMPLETE - {len(problems)} problem(s); Friday will not start:")
    for p in problems:
        print(f"  MISSING/UNSAFE  {p.removeprefix('missing ')}" if p.startswith("missing ")
              else f"  PROBLEM         {p}")
    print("Set them in the environment or .env (see .env.example), then re-run `friday check`.")
    return 1


async def _worker(settings: Settings) -> None:
    from friday.api.runtime import Runtime

    c = Container(settings)
    runtime = Runtime(c)
    await runtime.start(background=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    print(f"friday worker running: roles={','.join(settings.roles)} (Ctrl-C to drain and stop)")
    await stop.wait()
    await runtime.stop()
    await c.aclose()


async def _initdb(settings: Settings) -> None:
    c = Container(settings)
    await c.db.create_all()
    await c.aclose()
    print("tables created")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="friday")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("initdb")
    sub.add_parser("serve")
    worker = sub.add_parser("worker", help="run background roles without the HTTP server")
    worker.add_argument("--roles", default=None, help="api,task,voice,proactive,batch (CSV)")
    sub.add_parser("chat")
    args = parser.parse_args(argv)

    settings = Settings()
    setup_logging(settings.log_level, settings.log_json)

    if args.cmd == "check":
        return _check(settings)
    if args.cmd == "initdb":
        asyncio.run(_initdb(settings))
        return 0
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run(
            "friday.api.app:create_app", factory=True, host=settings.host, port=settings.port
        )
        return 0
    if args.cmd == "worker":
        if args.roles:
            settings = settings.model_copy(
                update={"roles": [r.strip() for r in args.roles.split(",") if r.strip()]}
            )
        asyncio.run(_worker(settings))
        return 0
    if args.cmd == "chat":
        try:
            chat = importlib.import_module("friday.channels.cli")
        except ModuleNotFoundError:
            print("simulator chat not implemented yet (friday/channels/cli.py:main)")
            return 1
        return int(chat.main() or 0)
    return 2


if __name__ == "__main__":
    sys.exit(main())
