"""`friday` command line.

    uv run friday check     # show mode + resolved providers + which modules exist
    uv run friday initdb    # create tables in FRIDAY_DATABASE_URL
    uv run friday serve     # run the API (needs friday.api.app:create_app)
    uv run friday chat      # local WhatsApp simulator chat (needs friday.channels.cli:main)

Owner: EM scaffold -> QA Engineer finalises the run commands.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import sys

from friday.core.config import Settings
from friday.core.container import FACTORIES, Container
from friday.core.logging import setup_logging


def _check(settings: Settings) -> int:
    c = Container(settings)
    print(f"mode: {settings.mode}   db: {settings.database_url}")
    for component in FACTORIES:
        provider = c.provider_for(component)
        try:
            path = c.factory_path(component)
        except Exception as e:  # noqa: BLE001
            print(f"  {component:20s} {provider:14s} ERROR {e}")
            continue
        status = "ok" if c.is_available(component) else "not implemented yet"
        print(f"  {component:20s} {provider:14s} {path:60s} {status}")
    problems = settings.live_problems() if settings.is_live else []
    for p in problems:
        print(f"  ! {p}")
    return 1 if problems else 0


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
