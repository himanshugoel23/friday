"""receptionist_spam: shared, anonymised spam-caller counts (keyed hash + count, no user id)

Revision ID: 0012_receptionist_spam
Revises: 0011_receptionist
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0012_receptionist_spam"
down_revision = "0011_receptionist"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "receptionist_spam",
        sa.Column("number_hash", sa.String(length=64), nullable=False),
        sa.Column("reports", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receptionist_spam")),
        sa.UniqueConstraint("number_hash", name="uq_receptionist_spam_number_hash"),
    )


def downgrade() -> None:
    op.drop_table("receptionist_spam")
