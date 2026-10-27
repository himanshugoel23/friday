"""documents, document_fields: photos and documents the user sent, as minimal confirmed fields

Revision ID: 0014_documents
Revises: 0013_evidence

docs/DOCUMENT_UNDERSTANDING.md. No column holds file bytes. document_fields.value and
documents.pointer_ref are encrypted text (field cipher); a passport number is stored masked only.
user_id is the erasure key; expires_at drives the retention job.
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0014_documents"
down_revision = "0013_evidence"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)


def _fk(table: str, col: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], [f"{target}.id"], name=op.f(f"fk_{table}_{col}_{target}"), ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("doc_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mime", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("injection_flag", sa.Boolean(), nullable=False),
        sa.Column("pointer_kind", sa.String(length=16), nullable=True),
        sa.Column("pointer_ref", sa.Text(), nullable=True),
        sa.Column("expires_at", _DT, nullable=True),
        sa.Column("confirmed_at", _DT, nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _fk("documents", "user_id", "users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index("ix_documents_user_status", "documents", ["user_id", "status"])
    op.create_index("ix_documents_expires", "documents", ["expires_at"])
    op.create_table(
        "document_fields",
        sa.Column("document_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("needs_confirm", sa.Boolean(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("masked", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _fk("document_fields", "document_id", "documents"),
        _fk("document_fields", "user_id", "users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_fields")),
    )
    op.create_index("ix_document_fields_doc", "document_fields", ["document_id"])
    op.create_index("ix_document_fields_user", "document_fields", ["user_id"])


def downgrade() -> None:
    op.drop_table("document_fields")
    op.drop_table("documents")
