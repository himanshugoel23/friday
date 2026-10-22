"""receptionist_configs, receptionist_messages, receptionist_blocks: the voicemail receptionist

Revision ID: 0011_receptionist
Revises: 0010_chatbot

Per-user setup (encrypted), messages taken from forwarded calls (personal text encrypted; caller
and number hashes are blind indexes) and the per-user block list. user_id is the erasure key.
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0011_receptionist"
down_revision = "0010_chatbot"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)
_JSON = sa.JSON().with_variant(sa.JSON(), "postgresql")


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"], ["users.id"], name=op.f(f"fk_{table}_user_id_users"), ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "receptionist_configs",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _user_fk("receptionist_configs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receptionist_configs")),
        sa.UniqueConstraint("user_id", name=op.f("uq_receptionist_configs_user_id")),
    )
    op.create_table(
        "receptionist_messages",
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("caller_hash", sa.String(length=64), nullable=True),
        sa.Column("caller_number", sa.Text(), nullable=True),
        sa.Column("caller_name", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("callback_number", sa.Text(), nullable=True),
        sa.Column("known_contact_name", sa.Text(), nullable=True),
        sa.Column("urgency", sa.String(length=8), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("notified_at", _DT, nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("reasons", _JSON, nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _user_fk("receptionist_messages"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receptionist_messages")),
    )
    op.create_index(
        "ix_receptionist_messages_user_created", "receptionist_messages", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_receptionist_messages_caller_created",
        "receptionist_messages",
        ["caller_hash", "created_at"],
    )
    op.create_table(
        "receptionist_blocks",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("number_hash", sa.String(length=64), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _user_fk("receptionist_blocks"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receptionist_blocks")),
        sa.UniqueConstraint("user_id", "number_hash", name="uq_receptionist_blocks"),
    )
    op.create_index(
        op.f("ix_receptionist_blocks_user_id"), "receptionist_blocks", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_receptionist_blocks_user_id"), table_name="receptionist_blocks")
    op.drop_table("receptionist_blocks")
    op.drop_index("ix_receptionist_messages_caller_created", table_name="receptionist_messages")
    op.drop_index("ix_receptionist_messages_user_created", table_name="receptionist_messages")
    op.drop_table("receptionist_messages")
    op.drop_table("receptionist_configs")
