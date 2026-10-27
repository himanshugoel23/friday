"""evidence_items, done_claims: proof attached to "done" messages

Revision ID: 0013_evidence
Revises: 0012_receptionist_spam

Per-user proof (docs/PROOF.md). summary and payload are encrypted text (field cipher); no raw
document or image bytes are stored (a screenshot is an object-store key, a receipt a sha-256).
user_id is the erasure key; expires_at drives the 90-day retention job.
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0013_evidence"
down_revision = "0012_receptionist_spam"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)
_JSON = sa.JSON().with_variant(sa.JSON(), "postgresql")


def _fk(table: str, col: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], [f"{target}.id"], name=op.f(f"fk_{table}_{col}_{target}"), ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "evidence_items",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("call_id", sa.String(length=32), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("object_key", sa.String(length=300), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("captured_at", _DT, nullable=False),
        sa.Column("expires_at", _DT, nullable=True),
        sa.Column("shareable", sa.Boolean(), nullable=False),
        sa.Column("redaction", sa.String(length=8), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _fk("evidence_items", "user_id", "users"),
        _fk("evidence_items", "task_id", "tasks"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_items")),
    )
    op.create_index("ix_evidence_items_task", "evidence_items", ["task_id"])
    op.create_index(
        "ix_evidence_items_user_captured", "evidence_items", ["user_id", "captured_at"]
    )
    op.create_index("ix_evidence_items_expires", "evidence_items", ["expires_at"])
    op.create_table(
        "done_claims",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("claim_type", sa.String(length=24), nullable=False),
        sa.Column("required_level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("evidence_ids", _JSON, nullable=True),
        sa.Column("missing", _JSON, nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _fk("done_claims", "user_id", "users"),
        _fk("done_claims", "task_id", "tasks"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_done_claims")),
    )
    op.create_index(op.f("ix_done_claims_user_id"), "done_claims", ["user_id"])
    op.create_index("ix_done_claims_task", "done_claims", ["task_id"], unique=True)


def downgrade() -> None:
    op.drop_table("done_claims")
    op.drop_table("evidence_items")
