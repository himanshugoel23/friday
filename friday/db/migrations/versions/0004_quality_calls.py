"""quality_calls: consented, redacted, encrypted call transcripts for the quality loop

Revision ID: 0004_quality_calls
Revises: 0003_task_role
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0004_quality_calls"
down_revision = "0003_task_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quality_calls",
        sa.Column("call_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("stored_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("expires_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("meta", sa.JSON().with_variant(sa.JSON(), "postgresql"), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("labels", sa.JSON().with_variant(sa.JSON(), "postgresql"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("rated_at", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("labelled_at", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_quality_calls_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quality_calls")),
        sa.UniqueConstraint("call_id", name=op.f("uq_quality_calls_call_id")),
    )
    with op.batch_alter_table("quality_calls", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_quality_calls_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_quality_calls_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("quality_calls", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quality_calls_user_id"))
        batch_op.drop_index(batch_op.f("ix_quality_calls_expires_at"))
    op.drop_table("quality_calls")
