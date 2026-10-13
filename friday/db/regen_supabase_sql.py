"""Regenerate deploy/supabase/schema.sql (Postgres DDL of every Alembic migration):
    uv run python -m friday.db.regen_supabase_sql
"""

from __future__ import annotations

import io
from pathlib import Path

from alembic import command
from alembic.config import Config

from friday.db.migrate import SCRIPT_LOCATION


def main() -> int:
    buf = io.StringIO()
    cfg = Config(output_buffer=buf)
    cfg.set_main_option("script_location", SCRIPT_LOCATION)
    cfg.set_main_option("sqlalchemy.url", "postgresql://u:p@localhost/db")  # dialect only
    command.upgrade(cfg, "head", sql=True)
    out = Path(__file__).resolve().parents[2] / "deploy" / "supabase" / "schema.sql"
    out.write_text(buf.getvalue(), encoding="utf-8")
    print(f"wrote {out} ({buf.getvalue().count('CREATE TABLE')} CREATE TABLE statements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
