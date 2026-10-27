"""urgent_escalation_configs, urgent_escalations: urgent-call escalation state

Revision ID: 0015_urgent_escalation
Revises: 0014_documents

docs/URGENT_ESCALATION.md. urgent_escalation_configs.config is encrypted JSON (the user's own number
and overrides). urgent_escalations holds the state machine only (no personal text); UNIQUE
(user_id, message_id) makes opening an escalation idempotent. user_id is the erasure key.
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0015_urgent_escalation"
down_revision = "0014_documents"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"], ["users.id"], name=op.f(f"fk_{table}_user_id_users"), ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "urgent_escalation_configs",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("opted_in", sa.Boolean(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _user_fk("urgent_escalation_configs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_urgent_escalation_configs")),
        sa.UniqueConstraint("user_id", name=op.f("uq_urgent_escalation_configs_user_id")),
    )
    op.create_table(
        "urgent_escalations",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("emergency", sa.Boolean(), nullable=False),
        sa.Column("alert_ok", sa.Boolean(), nullable=False),
        sa.Column("alert_sent_at", _DT, nullable=True),
        sa.Column("wait_s", sa.Integer(), nullable=False),
        sa.Column("max_calls", sa.Integer(), nullable=False),
        sa.Column("spacing_s", sa.Integer(), nullable=False),
        sa.Column("next_action_at", _DT, nullable=True),
        sa.Column("calls_made", sa.Integer(), nullable=False),
        sa.Column("in_flight", sa.Boolean(), nullable=False),
        sa.Column("last_call_at", _DT, nullable=True),
        sa.Column("last_call_result", sa.String(length=16), nullable=True),
        sa.Column("ack_at", _DT, nullable=True),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("finished_at", _DT, nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _user_fk("urgent_escalations"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_urgent_escalations")),
        sa.UniqueConstraint("user_id", "message_id", name="uq_urgent_escalations_user_message"),
    )
    op.create_index(op.f("ix_urgent_escalations_user_id"), "urgent_escalations", ["user_id"])
    op.create_index(
        "ix_urgent_escalations_due", "urgent_escalations", ["status", "next_action_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_urgent_escalations_due", table_name="urgent_escalations")
    op.drop_index(op.f("ix_urgent_escalations_user_id"), table_name="urgent_escalations")
    op.drop_table("urgent_escalations")
    op.drop_table("urgent_escalation_configs")
