"""consumer calls (W1): contacts, call requests, briefs, outcomes, attempts, strikes, global DNC

Revision ID: 0007_consumer_calls
Revises: 0006_google_connector

``call_dnc`` stores only a keyed hash of a number (no number, no user id). All other tables carry
``user_id`` (ON DELETE CASCADE) as the erasure key; phone numbers, names and message text are
encrypted columns (friday/calls/dbmodel.py).
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0007_consumer_calls"
down_revision = "0006_google_connector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_dnc",
        sa.Column("number_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.Column("created_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_dnc")),
        sa.UniqueConstraint("number_hash", name=op.f("uq_call_dnc_number_hash")),
    )
    op.create_table(
        "call_attempts",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=32), nullable=False),
        sa.Column("number_hash", sa.String(length=64), nullable=False),
        sa.Column("started_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_call_attempts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_attempts")),
    )
    with op.batch_alter_table("call_attempts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_call_attempts_number_hash"), ["number_hash"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_call_attempts_started_at"), ["started_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_call_attempts_user_id"), ["user_id"], unique=False)

    op.create_table(
        "call_requests",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("callee_kind", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("purpose_kind", sa.String(length=20), nullable=False),
        sa.Column("callee_ref", sa.Text(), nullable=True),
        sa.Column("callee_name", sa.Text(), nullable=True),
        sa.Column("callee_number", sa.Text(), nullable=True),
        sa.Column("callee_number_hash", sa.String(length=64), nullable=True),
        sa.Column("number_confirmed", sa.Boolean(), nullable=False),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=12), nullable=False),
        sa.Column("scheduled_for", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("parent_id", sa.String(length=32), nullable=True),
        sa.Column("callback_of", sa.String(length=32), nullable=True),
        sa.Column("group_members", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("source_message_id", sa.String(length=80), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("task_id", sa.String(length=32), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_call_requests_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_requests")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_call_requests_idempotency_key")),
    )
    with op.batch_alter_table("call_requests", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_call_requests_callee_number_hash"), ["callee_number_hash"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_call_requests_next_attempt_at"), ["next_attempt_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_call_requests_parent_id"), ["parent_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_call_requests_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_call_requests_user_id"), ["user_id"], unique=False)

    op.create_table(
        "call_strikes",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("created_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_call_strikes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_strikes")),
    )
    with op.batch_alter_table("call_strikes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_call_strikes_user_id"), ["user_id"], unique=False)

    op.create_table(
        "consumer_contacts",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("nicknames", sa.Text(), nullable=False),
        sa.Column("relationship", sa.String(length=40), nullable=True),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("number_hash", sa.String(length=64), nullable=False),
        sa.Column("confirmed_at", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_consumer_contacts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consumer_contacts")),
        sa.UniqueConstraint("user_id", "number_hash", name=op.f("uq_consumer_contacts_user_id")),
    )
    with op.batch_alter_table("consumer_contacts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_consumer_contacts_number_hash"), ["number_hash"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_consumer_contacts_user_id"), ["user_id"], unique=False)

    op.create_table(
        "call_briefs",
        sa.Column("request_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("approval_hash", sa.String(length=64), nullable=True),
        sa.Column("approved_at", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["call_requests.id"],
            name=op.f("fk_call_briefs_request_id_call_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_call_briefs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_briefs")),
        sa.UniqueConstraint("request_id", name=op.f("uq_call_briefs_request_id")),
    )
    with op.batch_alter_table("call_briefs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_call_briefs_user_id"), ["user_id"], unique=False)

    op.create_table(
        "call_outcomes",
        sa.Column("request_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("number_hash", sa.String(length=64), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("started_at", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("recording_ref", sa.Text(), nullable=True),
        sa.Column("transcript_ref", sa.Text(), nullable=True),
        sa.Column("created_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["call_requests.id"],
            name=op.f("fk_call_outcomes_request_id_call_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_call_outcomes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_outcomes")),
    )
    with op.batch_alter_table("call_outcomes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_call_outcomes_request_id"), ["request_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_call_outcomes_started_at"), ["started_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_call_outcomes_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("call_outcomes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_call_outcomes_user_id"))
        batch_op.drop_index(batch_op.f("ix_call_outcomes_started_at"))
        batch_op.drop_index(batch_op.f("ix_call_outcomes_request_id"))

    op.drop_table("call_outcomes")
    with op.batch_alter_table("call_briefs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_call_briefs_user_id"))

    op.drop_table("call_briefs")
    with op.batch_alter_table("consumer_contacts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_consumer_contacts_user_id"))
        batch_op.drop_index(batch_op.f("ix_consumer_contacts_number_hash"))

    op.drop_table("consumer_contacts")
    with op.batch_alter_table("call_strikes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_call_strikes_user_id"))

    op.drop_table("call_strikes")
    with op.batch_alter_table("call_requests", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_call_requests_user_id"))
        batch_op.drop_index(batch_op.f("ix_call_requests_status"))
        batch_op.drop_index(batch_op.f("ix_call_requests_parent_id"))
        batch_op.drop_index(batch_op.f("ix_call_requests_next_attempt_at"))
        batch_op.drop_index(batch_op.f("ix_call_requests_callee_number_hash"))

    op.drop_table("call_requests")
    with op.batch_alter_table("call_attempts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_call_attempts_user_id"))
        batch_op.drop_index(batch_op.f("ix_call_attempts_started_at"))
        batch_op.drop_index(batch_op.f("ix_call_attempts_number_hash"))

    op.drop_table("call_attempts")
    op.drop_table("call_dnc")
