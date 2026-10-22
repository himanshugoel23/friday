"""chatbot_sessions, chatbot_waitlist, chatbot_inbox: the WhatsApp chatbot pilot

Revision ID: 0010_chatbot
Revises: 0009_life_state

First-run state (keyed by a hash of the phone, no number), the pilot waitlist (hash only) and the
founder's review inbox (wishlist and support requests, text encrypted).
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0010_chatbot"
down_revision = "0009_life_state"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "chatbot_sessions",
        sa.Column("phone_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("step", sa.String(length=24), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("step_at", _DT, nullable=False),
        sa.Column("pending_kind", sa.String(length=24), nullable=True),
        sa.Column("pending", sa.Text(), nullable=True),
        sa.Column("last_hash", sa.String(length=32), nullable=True),
        sa.Column("refused_at", _DT, nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_chatbot_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chatbot_sessions")),
        sa.UniqueConstraint("phone_hash", name=op.f("uq_chatbot_sessions_phone_hash")),
    )
    op.create_index(op.f("ix_chatbot_sessions_user_id"), "chatbot_sessions", ["user_id"])

    op.create_table(
        "chatbot_waitlist",
        sa.Column("phone_hash", sa.String(length=64), nullable=False),
        sa.Column("first_seen_at", _DT, nullable=False),
        sa.Column("last_seen_at", _DT, nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chatbot_waitlist")),
        sa.UniqueConstraint("phone_hash", name=op.f("uq_chatbot_waitlist_phone_hash")),
    )

    op.create_table(
        "chatbot_inbox",
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_chatbot_inbox_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chatbot_inbox")),
    )
    op.create_index(op.f("ix_chatbot_inbox_user_id"), "chatbot_inbox", ["user_id"])
    op.create_index("ix_chatbot_inbox_kind_created", "chatbot_inbox", ["kind", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chatbot_inbox_kind_created", table_name="chatbot_inbox")
    op.drop_index(op.f("ix_chatbot_inbox_user_id"), table_name="chatbot_inbox")
    op.drop_table("chatbot_inbox")
    op.drop_table("chatbot_waitlist")
    op.drop_index(op.f("ix_chatbot_sessions_user_id"), table_name="chatbot_sessions")
    op.drop_table("chatbot_sessions")
