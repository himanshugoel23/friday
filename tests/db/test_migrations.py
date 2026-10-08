"""S-5: Alembic up/down, partition DDL, pool config, EXPLAIN on hot queries."""

from __future__ import annotations

import os
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect, text

from friday.db import migrate, partitions
from friday.db.base import Base

PG_URL = os.environ.get("FRIDAY_TEST_PG_URL")


def test_migrations_up_down_sqlite(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    import friday.db.tables  # noqa: F401

    names = set(inspect(eng).get_table_names())
    assert set(Base.metadata.tables) <= names | {"alembic_version"}
    assert "jobs" in names and "friday_numbers" in names
    cols = {c["name"] for c in inspect(eng).get_columns("users")}
    assert {"phone", "phone_hmac"} <= cols
    migrate.downgrade(url)
    assert set(inspect(eng).get_table_names()) <= {"alembic_version"}
    migrate.upgrade(url)  # re-runnable
    eng.dispose()


def test_models_match_migrations(tmp_path):
    """No model change without a migration (autogenerate sees no diff)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    url = f"sqlite+aiosqlite:///{tmp_path}/d.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/d.db")
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
    eng.dispose()


def test_partition_ddl_text():
    stmts = partitions.conversion_statements("messages", first=date(2026, 10, 1), months=2)
    sql = "\n".join(stmts)
    assert "PARTITION BY RANGE (at)" in sql
    assert "PRIMARY KEY (at, id)" in sql  # partition key is part of the PK
    assert "messages_new_p2026_10 PARTITION OF messages_new" in sql
    assert "FROM ('2026-10-01') TO ('2026-11-01')" in sql
    assert "RENAME CONSTRAINT messages_new_pkey TO pk_messages" in sql
    turns = "\n".join(partitions.conversion_statements("call_turns", first=date(2026, 12, 15)))
    assert "FROM ('2026-12-01') TO ('2027-01-01')" in turns  # year rollover
    assert "UNIQUE" not in turns.split("PARTITION BY")[0]
    assert partitions.partition_statements("audit_log", date(2026, 11, 20), 1) == [
        "CREATE TABLE IF NOT EXISTS audit_log_p2026_11 PARTITION OF audit_log "
        "FOR VALUES FROM ('2026-11-01') TO ('2026-12-01')"
    ]
    assert all(partitions.downgrade_statements(t) for t in partitions.PARTITIONED_TABLES)


def test_sqlite_database_ignores_pool_args():
    from friday.db import Database

    db = Database("sqlite+aiosqlite:///:memory:", pool_size=99)
    assert db.engine.dialect.name == "sqlite"
    from friday.db.session import async_url

    assert async_url("postgres://u@h/db") == "postgresql+asyncpg://u@h/db"
    assert async_url("postgresql://u@h/db") == "postgresql+asyncpg://u@h/db"


async def test_hot_queries_use_indexes(db):
    """EXPLAIN QUERY PLAN: lookups by blind index / queue claim use an index, not a scan."""
    import friday.db.tables  # noqa: F401

    async with db.engine.connect() as conn:
        for sql in (
            "SELECT id FROM users WHERE phone_hmac = 'x'",
            "SELECT id FROM people WHERE phone_hmac = 'x'",
            (
                "SELECT id FROM messages WHERE phone_hmac = 'x' AND direction = 'inbound' "
                "ORDER BY at"
            ),
            (
                "SELECT id FROM jobs WHERE status = 'queued' AND due_at <= '2026-01-01' "
                "ORDER BY priority"
            ),
            "SELECT id FROM call_memory WHERE business_phone_hmac = 'x'",
            "SELECT id FROM dnc_registry WHERE phone_hmac = 'x'",
            "SELECT id FROM tasks WHERE status = 'scheduled' AND next_attempt_at <= '2026-01-01'",
        ):
            plan = " ".join(
                str(r[-1]) for r in (await conn.execute(text("EXPLAIN QUERY PLAN " + sql)))
            )
            assert "USING" in plan and "SCAN" not in plan.replace("SCAN jobs USING", ""), (
                sql,
                plan,
            )


@pytest.mark.postgres
def test_partition_conversion_on_postgres():
    if not PG_URL:
        pytest.skip("FRIDAY_TEST_PG_URL not set")
    sync = PG_URL.replace("+asyncpg", "")
    eng = create_engine(sync)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    migrate.upgrade(PG_URL)
    with eng.connect() as conn:
        kinds = dict(
            conn.execute(
                text(
                    "SELECT relname, relkind FROM pg_class WHERE relname IN "
                    "('messages','call_turns','audit_log','cost_entries')"
                )
            ).all()
        )
    assert set(kinds.values()) == {"p"}
    migrate.downgrade(PG_URL)
    eng.dispose()
