"""life_events, life_commitments, mute_topics, life_followups: the per-user life state (W4)

Revision ID: 0009_life_state
Revises: 0006_google_connector

NOTE for the merge: workstreams W1 (0007) and W3 (0008) add their own revisions. The lead re-chains
``down_revision`` to the last of them so there is a single head.
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0009_life_state"
down_revision = "0006_google_connector"
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
        "life_events",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("start_at", _DT, nullable=False),
        sa.Column("end_at", _DT, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("protected", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("repeat", _JSON, nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _user_fk("life_events"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_life_events")),
        sa.UniqueConstraint("user_id", "source", "source_ref", name="uq_life_events_source_ref"),
    )
    op.create_index("ix_life_events_user_start", "life_events", ["user_id", "start_at"])

    op.create_table(
        "life_commitments",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("due_at", _DT, nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("repeat", _JSON, nullable=True),
        sa.Column("person", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _user_fk("life_commitments"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_life_commitments")),
    )
    op.create_index("ix_life_commitments_user_due", "life_commitments", ["user_id", "due_at"])

    op.create_table(
        "mute_topics",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("muted", sa.Boolean(), nullable=False),
        sa.Column("channel", sa.String(length=12), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        _user_fk("mute_topics"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mute_topics")),
        sa.UniqueConstraint("user_id", "topic", name="uq_mute_topics_user_topic"),
    )
    op.create_index(op.f("ix_mute_topics_user_id"), "mute_topics", ["user_id"])

    op.create_table(
        "life_followups",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("topic", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("due_at", _DT, nullable=False),
        sa.Column("sent_at", _DT, nullable=True),
        sa.Column("responded_at", _DT, nullable=True),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        _user_fk("life_followups"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_life_followups")),
        sa.UniqueConstraint("user_id", "key", name="uq_life_followups_user_key"),
    )
    op.create_index("ix_life_followups_user_sent", "life_followups", ["user_id", "sent_at"])


def downgrade() -> None:
    op.drop_index("ix_life_followups_user_sent", table_name="life_followups")
    op.drop_table("life_followups")
    op.drop_index(op.f("ix_mute_topics_user_id"), table_name="mute_topics")
    op.drop_table("mute_topics")
    op.drop_index("ix_life_commitments_user_due", table_name="life_commitments")
    op.drop_table("life_commitments")
    op.drop_index("ix_life_events_user_start", table_name="life_events")
    op.drop_table("life_events")
