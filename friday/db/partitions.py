"""Monthly range partitioning for the high-volume tables (S-5), Postgres only.

``messages``, ``call_turns``, ``audit_log`` and ``cost_entries`` grow with traffic and
are only ever read by recent time windows, so they are partitioned by month on ``at``
(retention can then drop whole partitions). Partitioned tables need the partition key in
every unique key, so the primary key becomes ``(id, at)`` and ``call_turns``' unique
``(call_id, seq)`` becomes a plain index.

* ``conversion_statements(table, months=...)`` - DDL to convert one table (rename-free:
  build ``<t>_new``, copy, drop the old, rename) - used by Alembic revision 0002.
* ``partition_statements(table, first, count)`` - ``CREATE TABLE IF NOT EXISTS ... PARTITION
  OF`` statements; the daily maintenance job calls ``ensure_partitions`` to stay ahead.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import MetaData, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import friday.db.tables  # noqa: F401
from friday.db.base import Base

PARTITIONED_TABLES = ("messages", "call_turns", "audit_log", "cost_entries")
KEY = "at"


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def partition_name(table: str, month: date) -> str:
    return f"{table}_p{month.year}_{month.month:02d}"


def partition_statements(table: str, first: date, count: int = 12) -> list[str]:
    out = []
    start = _month_start(first)
    for i in range(count):
        lo, hi = _add_months(start, i), _add_months(start, i + 1)
        out.append(
            f"CREATE TABLE IF NOT EXISTS {partition_name(table, lo)} PARTITION OF {table} "
            f"FOR VALUES FROM ('{lo.isoformat()}') TO ('{hi.isoformat()}')"
        )
    return out


def _partitioned_copy(table_name: str) -> Table:
    src = Base.metadata.tables[table_name]
    cols = []
    for c in src.columns:
        copy = c._copy()
        copy.primary_key = c.primary_key or c.name == KEY
        cols.append(copy)
    # a partitioned PK may not be a single autoincrement column of a regular table
    return Table(f"{table_name}_new", MetaData(), *cols)


def conversion_statements(table_name: str, *, first: date, months: int = 12) -> list[str]:
    """Convert an (empty or populated) regular table into a monthly-partitioned one."""
    src = Base.metadata.tables[table_name]
    new = _partitioned_copy(table_name)
    dialect = postgresql.dialect()
    create = str(CreateTable(new).compile(dialect=dialect)).strip()
    create = f"{create} PARTITION BY RANGE ({KEY})"
    cols = ", ".join(c.name for c in src.columns)
    stmts = [
        create,
        f"CREATE TABLE {table_name}_new_pdefault PARTITION OF {table_name}_new DEFAULT",
    ]
    stmts += [
        s.replace(f" {table_name} ", f" {table_name}_new ").replace(
            f" {table_name}_p", f" {table_name}_new_p"
        )
        for s in partition_statements(table_name, first, months)
    ]
    stmts += [
        f"INSERT INTO {table_name}_new ({cols}) SELECT {cols} FROM {table_name}",
        f"DROP TABLE {table_name}",
        f"ALTER TABLE {table_name}_new RENAME TO {table_name}",
        f"ALTER TABLE {table_name} RENAME CONSTRAINT {table_name}_new_pkey TO pk_{table_name}",
    ]
    for ix in sorted(src.indexes, key=lambda i: i.name or ""):
        stmts.append(str(CreateIndex(ix).compile(dialect=dialect)).strip().replace("\n", " "))
    # unique (call_id, seq) can't include the partition key -> keep it as a plain index
    for uc in src.constraints:
        if uc.__class__.__name__ == "UniqueConstraint" and KEY not in {c.name for c in uc.columns}:
            cols_ = ", ".join(c.name for c in uc.columns)
            stmts.append(
                f"CREATE INDEX ix_{table_name}_{'_'.join(c.name for c in uc.columns)} "
                f"ON {table_name} ({cols_})"
            )
    return stmts


def downgrade_statements(table_name: str) -> list[str]:
    """Back to a regular table (copy rows out of the partitioned parent)."""
    src = Base.metadata.tables[table_name]
    dialect = postgresql.dialect()
    old = Table(f"{table_name}_old", MetaData(), *[c._copy() for c in src.columns])
    cols = ", ".join(c.name for c in src.columns)
    return [
        str(CreateTable(old).compile(dialect=dialect)).strip(),
        f"INSERT INTO {table_name}_old ({cols}) SELECT {cols} FROM {table_name}",
        f"DROP TABLE {table_name}",
        f"ALTER TABLE {table_name}_old RENAME TO {table_name}",
    ]


async def ensure_partitions(conn, *, first: date, count: int = 3) -> int:  # noqa: ANN001
    """Daily maintenance: make sure the next ``count`` months exist (idempotent)."""
    from sqlalchemy import text

    n = 0
    for table in PARTITIONED_TABLES:
        for stmt in partition_statements(table, first, count):
            await conn.execute(text(stmt))
            n += 1
    return n
