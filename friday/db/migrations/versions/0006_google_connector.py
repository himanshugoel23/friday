"""google_connections + google_oauth_states: per-user Google OAuth (Calendar, Gmail read-only)

Revision ID: 0006_google_connector
Revises: 0005_quote_conversations
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0006_google_connector"
down_revision = "0005_quote_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_connections",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("google_sub_hmac", sa.String(length=64), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("scopes", sa.JSON().with_variant(sa.JSON(), "postgresql"), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("access_expires_at", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_used_at", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_google_connections_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_google_connections")),
        sa.UniqueConstraint("user_id", name=op.f("uq_google_connections_user_id")),
    )
    with op.batch_alter_table("google_connections", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_google_connections_google_sub_hmac"), ["google_sub_hmac"], unique=False
        )
    op.create_table(
        "google_oauth_states",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("code_verifier", sa.Text(), nullable=True),
        sa.Column("scopes", sa.JSON().with_variant(sa.JSON(), "postgresql"), nullable=False),
        sa.Column("expires_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column("used_at", friday.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("created_at", friday.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_google_oauth_states_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_google_oauth_states")),
    )
    with op.batch_alter_table("google_oauth_states", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_google_oauth_states_user_id"), ["user_id"])
        batch_op.create_index(batch_op.f("ix_google_oauth_states_expires_at"), ["expires_at"])


def downgrade() -> None:
    with op.batch_alter_table("google_oauth_states", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_google_oauth_states_expires_at"))
        batch_op.drop_index(batch_op.f("ix_google_oauth_states_user_id"))
    op.drop_table("google_oauth_states")
    with op.batch_alter_table("google_connections", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_google_connections_google_sub_hmac"))
    op.drop_table("google_connections")
