# ruff: noqa: E501
"""robin_concierge_requests, robin_concierge_audit, robin_concierge_docs: the human operations desk

Revision ID: 0021_concierge
Revises: 0020_robin_device

docs/ROBIN_CONCIERGE_DESK.md (C1, C6, lane 2 minimum). Requests, handoffs/shifts and the audit counts are encrypted JSON
(``data``); plain columns are ids, state words, times and hashes. The audit table is an append-only hash chain (``seq`` unique).
Never stored: message text outside the encrypted request, phone numbers, audio.
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0021_concierge"
down_revision = "0020_robin_device"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)


def _tail(table: str) -> list:
    return [
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    for leftover in ("robin_concierge_docs", "robin_concierge_audit", "robin_concierge_requests"):
        op.execute(f"DROP TABLE IF EXISTS {leftover}")
    op.create_table(
        "robin_concierge_requests",
        sa.Column("family_id", sa.String(length=32), nullable=False),
        sa.Column("parent_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("lane", sa.String(length=16), nullable=False),
        sa.Column("claimed_by", sa.String(length=48), nullable=True),
        sa.Column("due_at", _DT, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        *_tail("robin_concierge_requests"),
    )
    op.create_index(op.f("ix_robin_concierge_requests_family_id"), "robin_concierge_requests", ["family_id"])
    op.create_index(op.f("ix_robin_concierge_requests_parent_id"), "robin_concierge_requests", ["parent_id"])
    op.create_index(op.f("ix_robin_concierge_requests_status"), "robin_concierge_requests", ["status"])
    op.create_table(
        "robin_concierge_audit",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("at", _DT, nullable=False),
        sa.Column("staff_id", sa.String(length=48), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("target_id", sa.String(length=48), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        *_tail("robin_concierge_audit"),
        sa.UniqueConstraint("seq", name="uq_robin_concierge_audit_seq"),
    )
    op.create_index(op.f("ix_robin_concierge_audit_staff_id"), "robin_concierge_audit", ["staff_id"])
    op.create_table(
        "robin_concierge_docs",
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=48), nullable=False),
        sa.Column("parent_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        *_tail("robin_concierge_docs"),
        sa.UniqueConstraint("kind", "target_id", name="uq_robin_concierge_docs_kind_target"),
    )
    op.create_index(op.f("ix_robin_concierge_docs_kind"), "robin_concierge_docs", ["kind"])
    op.create_index(op.f("ix_robin_concierge_docs_parent_id"), "robin_concierge_docs", ["parent_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_robin_concierge_docs_parent_id"), table_name="robin_concierge_docs")
    op.drop_index(op.f("ix_robin_concierge_docs_kind"), table_name="robin_concierge_docs")
    op.drop_table("robin_concierge_docs")
    op.drop_index(op.f("ix_robin_concierge_audit_staff_id"), table_name="robin_concierge_audit")
    op.drop_table("robin_concierge_audit")
    op.drop_index(op.f("ix_robin_concierge_requests_status"), table_name="robin_concierge_requests")
    op.drop_index(op.f("ix_robin_concierge_requests_parent_id"), table_name="robin_concierge_requests")
    op.drop_index(op.f("ix_robin_concierge_requests_family_id"), table_name="robin_concierge_requests")
    op.drop_table("robin_concierge_requests")
