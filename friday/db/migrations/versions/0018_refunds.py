"""refund_cases, refund_events, refund_evidence, refund_nudges: refund and cancellation tracking

Revision ID: 0018_refunds
Revises: 0017_trips

docs/REFUNDS.md. No column holds a file or document text. Vendor name, the user-typed vendor number,
notes, the follow-up proposal, evidence summaries/payloads and reminder text are encrypted text
(field cipher). Amounts are paise. user_id is the erasure key.
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0018_refunds"
down_revision = "0017_trips"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)


def _fk(table: str, col: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], [f"{target}.id"], name=op.f(f"fk_{table}_{col}_{target}"), ondelete="CASCADE"
    )


def _id() -> sa.Column:
    return sa.Column("id", sa.String(length=32), nullable=False)


def upgrade() -> None:
    # A first run that stopped half-way (SQLite DDL is not transactional) leaves these tables behind
    # while the version is still 0017; nothing can be in them yet, so start clean.
    for leftover in ("refund_nudges", "refund_evidence", "refund_events", "refund_cases"):
        op.execute(f"DROP TABLE IF EXISTS {leftover}")
    op.create_table(
        "refund_cases",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("origin", sa.String(length=14), nullable=False),
        sa.Column("origin_ref", sa.String(length=64), nullable=True),
        sa.Column("vendor_name", sa.Text(), nullable=False),
        sa.Column("amount_expected_paise", sa.Integer(), nullable=True),
        sa.Column("amount_received_paise", sa.Integer(), nullable=True),
        sa.Column("promised_date", sa.Date(), nullable=True),
        sa.Column("promised_amount_paise", sa.Integer(), nullable=True),
        sa.Column("paid_with_bank", sa.Text(), nullable=True),
        sa.Column("user_number", sa.Text(), nullable=True),
        sa.Column("task_id", sa.String(length=32), nullable=True),
        sa.Column("state_epoch", sa.Integer(), nullable=False),
        sa.Column("state_changed_at", _DT, nullable=False),
        sa.Column("closed_reason", sa.String(length=20), nullable=True),
        sa.Column("closed_basis", sa.String(length=8), nullable=True),
        sa.Column("proposal", sa.Text(), nullable=True),
        sa.Column("chase_count", sa.Integer(), nullable=False),
        sa.Column("muted", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        _id(),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _fk("refund_cases", "user_id", "users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refund_cases")),
    )
    op.create_index("ix_refund_cases_user_id", "refund_cases", ["user_id"])
    op.create_index("ix_refund_cases_user_state", "refund_cases", ["user_id", "state"])
    op.create_index("ix_refund_cases_origin", "refund_cases", ["user_id", "origin", "origin_ref"])
    op.create_table(
        "refund_events",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("from_state", sa.String(length=20), nullable=True),
        sa.Column("to_state", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("at", _DT, nullable=False),
        _id(),
        _fk("refund_events", "user_id", "users"),
        _fk("refund_events", "case_id", "refund_cases"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refund_events")),
    )
    op.create_index("ix_refund_events_user_id", "refund_events", ["user_id"])
    op.create_index("ix_refund_events_case", "refund_events", ["case_id"])
    op.create_table(
        "refund_evidence",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("amount_paise", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("proof_item_id", sa.String(length=32), nullable=True),
        sa.Column("captured_at", _DT, nullable=False),
        _id(),
        _fk("refund_evidence", "user_id", "users"),
        _fk("refund_evidence", "case_id", "refund_cases"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refund_evidence")),
    )
    op.create_index("ix_refund_evidence_user_id", "refund_evidence", ["user_id"])
    op.create_index("ix_refund_evidence_case", "refund_evidence", ["case_id"])
    op.create_table(
        "refund_nudges",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("sent_at", _DT, nullable=False),
        _id(),
        _fk("refund_nudges", "user_id", "users"),
        _fk("refund_nudges", "case_id", "refund_cases"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refund_nudges")),
        sa.UniqueConstraint("user_id", "key", name="uq_refund_nudges_user_key"),
    )
    op.create_index("ix_refund_nudges_user_id", "refund_nudges", ["user_id"])
    op.create_index("ix_refund_nudges_user_sent", "refund_nudges", ["user_id", "sent_at"])


def downgrade() -> None:
    op.drop_table("refund_nudges")
    op.drop_table("refund_evidence")
    op.drop_table("refund_events")
    op.drop_table("refund_cases")
