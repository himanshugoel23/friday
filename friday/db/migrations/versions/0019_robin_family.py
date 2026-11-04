"""robin_families, robin_members, robin_consents, robin_records: Robin family core

Revision ID: 0019_robin_family
Revises: 0018_refunds

docs/ROBIN_FAMILY_CORE.md. robin_families.data, robin_members.data and robin_records.data are encrypted
JSON (phones, names, medicines, answers, the safe-word hash). robin_members.phone_hash is a keyed hash
for lookup. user_id (the child) is the erasure key.
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0019_robin_family"
down_revision = "0018_refunds"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)


def _fk(table: str, col: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], [f"{target}.id"], name=op.f(f"fk_{table}_{col}_{target}"), ondelete="CASCADE"
    )


def _tail(table: str) -> list:
    return [
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    for leftover in ("robin_records", "robin_consents", "robin_members", "robin_families"):
        op.execute(f"DROP TABLE IF EXISTS {leftover}")
    op.create_table(
        "robin_families",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        *_tail("robin_families"),
        _fk("robin_families", "user_id", "users"),
    )
    op.create_index(op.f("ix_robin_families_user_id"), "robin_families", ["user_id"])
    op.create_table(
        "robin_members",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("family_id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("phone_hash", sa.String(length=64), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        *_tail("robin_members"),
        _fk("robin_members", "user_id", "users"),
        _fk("robin_members", "family_id", "robin_families"),
    )
    op.create_index(op.f("ix_robin_members_user_id"), "robin_members", ["user_id"])
    op.create_index(op.f("ix_robin_members_family_id"), "robin_members", ["family_id"])
    op.create_index(op.f("ix_robin_members_phone_hash"), "robin_members", ["phone_hash"])
    op.create_table(
        "robin_consents",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("family_id", sa.String(length=32), nullable=False),
        sa.Column("member_id", sa.String(length=32), nullable=False),
        sa.Column("item", sa.String(length=32), nullable=False),
        sa.Column("given_at", _DT, nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("given_by", sa.String(length=16), nullable=False),
        sa.Column("withdrawn_at", _DT, nullable=True),
        *_tail("robin_consents"),
        _fk("robin_consents", "user_id", "users"),
        _fk("robin_consents", "family_id", "robin_families"),
        _fk("robin_consents", "member_id", "robin_members"),
        sa.UniqueConstraint("member_id", "item", name="uq_robin_consents_member_item"),
    )
    op.create_index(op.f("ix_robin_consents_user_id"), "robin_consents", ["user_id"])
    op.create_index(op.f("ix_robin_consents_family_id"), "robin_consents", ["family_id"])
    op.create_table(
        "robin_records",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("family_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("at", _DT, nullable=False),
        sa.Column("due_at", _DT, nullable=True),
        sa.Column("data", sa.Text(), nullable=False),
        *_tail("robin_records"),
        _fk("robin_records", "user_id", "users"),
        _fk("robin_records", "family_id", "robin_families"),
        sa.UniqueConstraint("family_id", "kind", "key", name="uq_robin_records_family_kind_key"),
    )
    op.create_index(op.f("ix_robin_records_user_id"), "robin_records", ["user_id"])
    op.create_index("ix_robin_records_due", "robin_records", ["kind", "status", "due_at"])
    op.create_index("ix_robin_records_family_kind", "robin_records", ["family_id", "kind", "at"])


def downgrade() -> None:
    op.drop_index("ix_robin_records_family_kind", table_name="robin_records")
    op.drop_index("ix_robin_records_due", table_name="robin_records")
    op.drop_index(op.f("ix_robin_records_user_id"), table_name="robin_records")
    op.drop_table("robin_records")
    op.drop_index(op.f("ix_robin_consents_family_id"), table_name="robin_consents")
    op.drop_index(op.f("ix_robin_consents_user_id"), table_name="robin_consents")
    op.drop_table("robin_consents")
    op.drop_index(op.f("ix_robin_members_phone_hash"), table_name="robin_members")
    op.drop_index(op.f("ix_robin_members_family_id"), table_name="robin_members")
    op.drop_index(op.f("ix_robin_members_user_id"), table_name="robin_members")
    op.drop_table("robin_members")
    op.drop_index(op.f("ix_robin_families_user_id"), table_name="robin_families")
    op.drop_table("robin_families")
