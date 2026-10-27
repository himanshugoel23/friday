"""drive_links, drive_folders, drive_shares: pointers for the family's own Google Drive

Revision ID: 0016_family_drive
Revises: 0014_documents

docs/FAMILY_DRIVE.md. No column holds file bytes or a token. Drive ids and e-mails are encrypted
text (field cipher). user_id is the erasure key. NOTE: 0015_urgent_escalation is built in parallel;
when it is merged, set down_revision to "0015_urgent_escalation" (and fix doctor's chain comment).
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0016_family_drive"
down_revision = "0015_urgent_escalation"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)


def _fk(table: str, col: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], [f"{target}.id"], name=op.f(f"fk_{table}_{col}_{target}"), ondelete="CASCADE"
    )


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "drive_links",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("root_folder_id", sa.Text(), nullable=True),
        sa.Column("connected_at", _DT, nullable=False),
        *_base(),
        _fk("drive_links", "user_id", "users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drive_links")),
        sa.UniqueConstraint("user_id", name=op.f("uq_drive_links_user_id")),
    )
    op.create_table(
        "drive_folders",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("path_key", sa.String(length=160), nullable=False),
        sa.Column("folder_id", sa.Text(), nullable=False),
        *_base(),
        _fk("drive_folders", "user_id", "users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drive_folders")),
        sa.UniqueConstraint("user_id", "path_key", name="uq_drive_folders_user_key"),
    )
    op.create_index("ix_drive_folders_user_id", "drive_folders", ["user_id"])
    op.create_table(
        "drive_shares",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("permission_id", sa.Text(), nullable=True),
        sa.Column("expires_at", _DT, nullable=False),
        sa.Column("decided_at", _DT, nullable=True),
        *_base(),
        _fk("drive_shares", "user_id", "users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drive_shares")),
    )
    op.create_index("ix_drive_shares_user_status", "drive_shares", ["user_id", "status"])


def downgrade() -> None:
    op.drop_table("drive_shares")
    op.drop_table("drive_folders")
    op.drop_table("drive_links")
