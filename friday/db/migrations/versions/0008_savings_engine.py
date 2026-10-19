"""savings engine: wallet_cards, card_rules, bills, savings_ledger

Revision ID: 0008_savings_engine
Revises: 0006_google_connector

NOTE FOR THE LEAD: workstream W1 owns 0007. When both branches are merged, change
``down_revision`` below to W1's 0007 revision id so the chain stays linear (one head).
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0008_savings_engine"
down_revision = "0007_consumer_calls"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(sa.JSON(), "postgresql")
_TS = friday.db.base.UTCDateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "wallet_cards",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("card_key_hmac", sa.String(length=64), nullable=False),
        sa.Column("bank", sa.Text(), nullable=False),
        sa.Column("card_name", sa.Text(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("updated_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_wallet_cards_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallet_cards")),
        sa.UniqueConstraint("user_id", "card_key_hmac", name=op.f("uq_wallet_cards_user_id")),
    )
    with op.batch_alter_table("wallet_cards", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_wallet_cards_user_id"), ["user_id"], unique=False)

    op.create_table(
        "card_rules",
        sa.Column("card_key", sa.String(length=160), nullable=False),
        sa.Column("scope", sa.String(length=200), nullable=False),
        sa.Column("bank", sa.String(length=80), nullable=False),
        sa.Column("card_name", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("reward_type", sa.String(length=12), nullable=False),
        sa.Column("rate_bp", sa.Integer(), nullable=False),
        sa.Column("monthly_cap_paise", sa.Integer(), nullable=True),
        sa.Column("per_txn_cap_paise", sa.Integer(), nullable=True),
        sa.Column("min_spend_paise", sa.Integer(), nullable=False),
        sa.Column("exclusions", _JSON, nullable=False),
        sa.Column("merchants", _JSON, nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=True),
        sa.Column("verified_by", sa.String(length=100), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("updated_at", _TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_rules")),
        sa.UniqueConstraint("card_key", "scope", name=op.f("uq_card_rules_card_key")),
    )
    with op.batch_alter_table("card_rules", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_card_rules_card_key"), ["card_key"], unique=False)

    op.create_table(
        "bills",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("updated_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_bills_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bills")),
    )
    with op.batch_alter_table("bills", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_bills_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_bills_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_bills_due_on"), ["due_on"], unique=False)

    op.create_table(
        "savings_ledger",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("fingerprint_hmac", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_savings_ledger_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_savings_ledger")),
        sa.UniqueConstraint("user_id", "fingerprint_hmac", name=op.f("uq_savings_ledger_user_id")),
    )
    with op.batch_alter_table("savings_ledger", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_savings_ledger_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_savings_ledger_month"), ["month"], unique=False)
        batch_op.create_index(batch_op.f("ix_savings_ledger_outcome"), ["outcome"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("savings_ledger", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_savings_ledger_outcome"))
        batch_op.drop_index(batch_op.f("ix_savings_ledger_month"))
        batch_op.drop_index(batch_op.f("ix_savings_ledger_user_id"))
    op.drop_table("savings_ledger")
    with op.batch_alter_table("bills", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_bills_due_on"))
        batch_op.drop_index(batch_op.f("ix_bills_status"))
        batch_op.drop_index(batch_op.f("ix_bills_user_id"))
    op.drop_table("bills")
    with op.batch_alter_table("card_rules", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_card_rules_card_key"))
    op.drop_table("card_rules")
    with op.batch_alter_table("wallet_cards", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_wallet_cards_user_id"))
    op.drop_table("wallet_cards")
