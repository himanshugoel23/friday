"""robin_device_states, robin_device_codes: Robin device side persistence

Revision ID: 0020_robin_device
Revises: 0019_robin_family

docs/ROBIN_PHASE1_BACKLOG.md T02. robin_device_states.data is encrypted JSON (events as enums/counts/timestamps,
prompts, fired ranks, shadow clock, counters, trusted-number hashes, audit of what the child was told);
token_hash is the SHA-256 of the device token, never the token. robin_device_codes holds pairing codes as a
keyed hash with an expiry. Never stored: message text, contact names, digits, audio.
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0020_robin_device"
down_revision = "0019_robin_family"
branch_labels = None
depends_on = None

_DT = friday.db.base.UTCDateTime(timezone=True)


def _tail(table: str) -> list:
    return [
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("updated_at", _DT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    for leftover in ("robin_device_codes", "robin_device_states"):
        op.execute(f"DROP TABLE IF EXISTS {leftover}")
    op.create_table(
        "robin_device_states",
        sa.Column("parent_id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        *_tail("robin_device_states"),
    )
    op.create_index(op.f("ix_robin_device_states_parent_id"), "robin_device_states", ["parent_id"], unique=True)
    op.create_index(op.f("ix_robin_device_states_token_hash"), "robin_device_states", ["token_hash"])
    op.create_table(
        "robin_device_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("parent_id", sa.String(length=32), nullable=False),
        sa.Column("expires_ms", sa.BigInteger(), nullable=False),
        *_tail("robin_device_codes"),
        sa.UniqueConstraint("code_hash", name=op.f("uq_robin_device_codes_code_hash")),
    )
    op.create_index(op.f("ix_robin_device_codes_parent_id"), "robin_device_codes", ["parent_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_robin_device_codes_parent_id"), table_name="robin_device_codes")
    op.drop_table("robin_device_codes")
    op.drop_index(op.f("ix_robin_device_states_token_hash"), table_name="robin_device_states")
    op.drop_index(op.f("ix_robin_device_states_parent_id"), table_name="robin_device_states")
    op.drop_table("robin_device_states")
