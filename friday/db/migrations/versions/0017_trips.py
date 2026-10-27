"""trips, trip_legs, trip_tasks, flight_watch, trip_nudges, card_perks: the trip timeline

Revision ID: 0017_trips
Revises: 0016_family_drive

docs/TRIP_TIMELINE.md. No column holds a file or document text. Titles, airports, booking
references, hotel phone and address, the pickup address and message text are encrypted text (field
cipher); the leg's booking reference also has a blind index. user_id is the erasure key.
card_perks is shared (no personal data, no revenue column).
"""

import sqlalchemy as sa
from alembic import op

import friday.db.base

revision = "0017_trips"
down_revision = "0016_family_drive"
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
        "trips",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_from", sa.String(length=8), nullable=False),
        sa.Column("travel_minutes", sa.Integer(), nullable=True),
        sa.Column("pickup_address", sa.Text(), nullable=True),
        sa.Column("muted", sa.Boolean(), nullable=False),
        *_base(),
        _fk("trips", "user_id", "users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trips")),
    )
    op.create_index("ix_trips_user_status", "trips", ["user_id", "status"])
    op.create_table(
        "trip_legs",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("trip_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("starts_at", _DT, nullable=False),
        sa.Column("ends_at", _DT, nullable=True),
        sa.Column("tz", sa.String(length=40), nullable=False),
        sa.Column("end_tz", sa.String(length=40), nullable=True),
        sa.Column("origin", sa.Text(), nullable=True),
        sa.Column("dest", sa.Text(), nullable=True),
        sa.Column("ref", sa.Text(), nullable=True),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("international", sa.Boolean(), nullable=False),
        sa.Column("time_known", sa.Boolean(), nullable=False),
        sa.Column("document_id", sa.String(length=32), nullable=True),
        sa.Column("pointer_kind", sa.String(length=16), nullable=True),
        sa.Column("dedupe_hmac", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        *_base(),
        _fk("trip_legs", "user_id", "users"),
        _fk("trip_legs", "trip_id", "trips"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_legs")),
        sa.UniqueConstraint("user_id", "dedupe_hmac", name="uq_trip_legs_user_dedupe"),
    )
    op.create_index("ix_trip_legs_user_id", "trip_legs", ["user_id"])
    op.create_index("ix_trip_legs_trip", "trip_legs", ["trip_id"])
    op.create_table(
        "trip_tasks",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("trip_id", sa.String(length=32), nullable=False),
        sa.Column("leg_id", sa.String(length=32), nullable=True),
        sa.Column("kind", sa.String(length=14), nullable=False),
        sa.Column("due_at", _DT, nullable=False),
        sa.Column("expires_at", _DT, nullable=False),
        sa.Column("state", sa.String(length=14), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=True),
        sa.Column("evidence_ids", sa.JSON().with_variant(sa.JSON(), "postgresql"), nullable=False),
        sa.Column("dedupe_key", sa.String(length=120), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("params", sa.Text(), nullable=False),
        *_base(),
        _fk("trip_tasks", "user_id", "users"),
        _fk("trip_tasks", "trip_id", "trips"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_tasks")),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_trip_tasks_user_dedupe"),
    )
    op.create_index("ix_trip_tasks_user_id", "trip_tasks", ["user_id"])
    op.create_index("ix_trip_tasks_trip", "trip_tasks", ["trip_id"])
    op.create_index("ix_trip_tasks_due", "trip_tasks", ["due_at"])
    op.create_table(
        "flight_watch",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("trip_id", sa.String(length=32), nullable=False),
        sa.Column("leg_id", sa.String(length=32), nullable=False),
        sa.Column("last_status", sa.String(length=14), nullable=True),
        sa.Column("last_checked_at", _DT, nullable=True),
        sa.Column("next_check_at", _DT, nullable=True),
        sa.Column("delay_minutes", sa.Integer(), nullable=False),
        sa.Column("changed_notified", sa.Boolean(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("info", sa.Text(), nullable=False),
        *_base(),
        _fk("flight_watch", "user_id", "users"),
        _fk("flight_watch", "trip_id", "trips"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flight_watch")),
        sa.UniqueConstraint("leg_id", name="uq_flight_watch_leg"),
    )
    op.create_index("ix_flight_watch_user_id", "flight_watch", ["user_id"])
    op.create_index("ix_flight_watch_next", "flight_watch", ["next_check_at"])
    op.create_table(
        "trip_nudges",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("trip_id", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=140), nullable=False),
        sa.Column("topic", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("sent_at", _DT, nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        _fk("trip_nudges", "user_id", "users"),
        _fk("trip_nudges", "trip_id", "trips"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_nudges")),
        sa.UniqueConstraint("user_id", "key", name="uq_trip_nudges_user_key"),
    )
    op.create_index("ix_trip_nudges_user_id", "trip_nudges", ["user_id"])
    op.create_index("ix_trip_nudges_user_sent", "trip_nudges", ["user_id", "sent_at"])
    op.create_table(
        "card_perks",
        sa.Column("card_key", sa.String(length=160), nullable=False),
        sa.Column("perk", sa.String(length=20), nullable=False),
        sa.Column("bank", sa.String(length=80), nullable=False),
        sa.Column("card_name", sa.String(length=80), nullable=False),
        sa.Column("visits_per_period", sa.Integer(), nullable=True),
        sa.Column("period", sa.String(length=12), nullable=False),
        sa.Column("conditions_text", sa.Text(), nullable=False),
        sa.Column("min_spend_paise", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=True),
        sa.Column("verified_by", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=False),
        *_base(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_perks")),
        sa.UniqueConstraint("card_key", "perk", name="uq_card_perks_card_perk"),
    )
    op.create_index("ix_card_perks_card_key", "card_perks", ["card_key"])


def downgrade() -> None:
    op.drop_table("card_perks")
    op.drop_table("trip_nudges")
    op.drop_table("flight_watch")
    op.drop_table("trip_tasks")
    op.drop_table("trip_legs")
    op.drop_table("trips")
