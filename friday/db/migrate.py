"""Run Alembic migrations programmatically (S-5).

    uv run python -m friday.db.migrate up        # alembic upgrade head
    uv run python -m friday.db.migrate down      # downgrade to base (dev only!)
    uv run python -m friday.db.migrate revision "add x"   # autogenerate (dev)
    uv run python -m friday.db.migrate rls       # Postgres: Row Level Security on every table

Deploys run ``up`` as a release step before the new version starts. ``create_all`` is
for dev/tests only.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from friday.core.config import Settings
from friday.db.session import Database

SCRIPT_LOCATION = str(Path(__file__).with_name("migrations"))


def _config(engine) -> Config:  # noqa: ANN001
    cfg = Config()
    cfg.set_main_option("script_location", SCRIPT_LOCATION)
    cfg.attributes["engine"] = engine
    return cfg


def _run(fn, url: str, *args, **kw) -> None:  # noqa: ANN001
    import asyncio

    async def go() -> None:
        db = Database(url)
        try:
            # alembic's env.py drives the async engine itself; call in a thread so its
            # own asyncio.run() has a free loop.
            await asyncio.to_thread(fn, _config(db.engine), *args, **kw)
        finally:
            await db.dispose()

    asyncio.run(go())


def upgrade(url: str, revision: str = "head") -> None:
    _run(command.upgrade, url, revision)


def downgrade(url: str, revision: str = "base") -> None:
    _run(command.downgrade, url, revision)


def revision(url: str, message: str) -> None:
    _run(command.revision, url, message=message, autogenerate=True)


def enable_rls(url: str) -> int:
    """Postgres/Supabase: switch Row Level Security ON for every table of the app (no policies),
    so the public Data API (anon / authenticated keys) can read nothing; the server's database
    owner role bypasses RLS. Idempotent. Returns the number of tables."""
    import asyncio

    from sqlalchemy import text

    import friday.db.tables  # noqa: F401  (register tables)
    from friday.db.base import Base

    if not url.startswith("postgresql"):
        raise SystemExit("rls is for PostgreSQL (FRIDAY_DATABASE_URL)")
    names = sorted({t.name for t in Base.metadata.sorted_tables} | {"alembic_version"})

    async def go() -> int:
        db = Database(url)
        try:
            async with db.engine.begin() as conn:
                for name in names:
                    await conn.execute(text(f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY'))
        finally:
            await db.dispose()
        return len(names)

    return asyncio.run(go())


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    url = Settings().database_url
    if not args or args[0] == "up":
        upgrade(url)
    elif args[0] == "down":
        downgrade(url)
    elif args[0] == "rls":
        print(f"row level security enabled on {enable_rls(url)} tables")
    elif args[0] == "revision" and len(args) > 1:
        revision(url, args[1])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
