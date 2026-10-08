"""tasks.role (fan-out family role; BUG-2) + calls.from_number (BUG-16)

Revision ID: 0003_task_role
Revises: 0002_partitions
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_task_role"
down_revision = "0002_partitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("role", sa.String(length=24), nullable=True))
    with op.batch_alter_table("calls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("from_number", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("calls", schema=None) as batch_op:
        batch_op.drop_column("from_number")
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_column("role")
