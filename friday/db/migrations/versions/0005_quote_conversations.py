"""quote_conversations: WhatsApp quotes flow state (one row per request)

Revision ID: 0005_quote_conversations
Revises: 0004_quality_calls
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0005_quote_conversations"
down_revision = "0004_quality_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quote_conversations",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("counted_at", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("created_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_quote_conversations_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_conversations")),
    )
    with op.batch_alter_table("quote_conversations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_quote_conversations_user_id"), ["user_id"])
        batch_op.create_index(batch_op.f("ix_quote_conversations_state"), ["state"])
        batch_op.create_index(batch_op.f("ix_quote_conversations_active"), ["active"])
        batch_op.create_index(batch_op.f("ix_quote_conversations_counted_at"), ["counted_at"])


def downgrade() -> None:
    with op.batch_alter_table("quote_conversations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quote_conversations_counted_at"))
        batch_op.drop_index(batch_op.f("ix_quote_conversations_active"))
        batch_op.drop_index(batch_op.f("ix_quote_conversations_state"))
        batch_op.drop_index(batch_op.f("ix_quote_conversations_user_id"))
    op.drop_table("quote_conversations")
