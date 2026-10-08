"""monthly partitions for messages, call_turns, audit_log, cost_entries (Postgres only)

Revision ID: 0002_partitions
Revises: 0001_baseline
"""

from datetime import date

from alembic import op

from friday.db import partitions

revision = "0002_partitions"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    first = date.today().replace(day=1)
    for table in partitions.PARTITIONED_TABLES:
        for stmt in partitions.conversion_statements(table, first=first, months=12):
            op.execute(stmt)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in partitions.PARTITIONED_TABLES:
        for stmt in partitions.downgrade_statements(table):
            op.execute(stmt)
