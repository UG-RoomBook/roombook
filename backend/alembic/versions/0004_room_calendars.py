"""Add calendars without inventing hours or changing existing bookings."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rooms",
        sa.Column("hours_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "room_weekly_hours",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="valid_weekday"),
        sa.CheckConstraint(
            "0 <= start_minute AND start_minute < end_minute AND end_minute <= 1440",
            name="valid_minutes",
        ),
        postgresql.ExcludeConstraint(
            ("room_id", "="),
            ("weekday", "="),
            (sa.text("int4range(start_minute, end_minute, '[)')"), "&&"),
            name="room_weekly_hours_interval_excl",
        ),
    )
    op.create_table(
        "room_date_exceptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
        sa.UniqueConstraint("room_id", "date"),
    )
    op.create_table(
        "room_exception_hours",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exception_id", sa.Uuid(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["exception_id"], ["room_date_exceptions.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "0 <= start_minute AND start_minute < end_minute AND end_minute <= 1440",
            name="valid_minutes",
        ),
        postgresql.ExcludeConstraint(
            ("exception_id", "="),
            (sa.text("int4range(start_minute, end_minute, '[)')"), "&&"),
            name="room_exception_hours_interval_excl",
        ),
    )
    op.create_table(
        "room_closures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
        sa.CheckConstraint("starts_at < ends_at", name="valid_interval"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="nonempty_reason"),
    )
    op.create_index("ix_room_closures_room_id_starts_at", "room_closures", ["room_id", "starts_at"])


def downgrade() -> None:
    # Keep populated operational data. Application rollback leaves this schema in
    # place; a deliberate archived-data removal is a separate operator decision.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM room_weekly_hours)
             OR EXISTS (SELECT 1 FROM room_date_exceptions)
             OR EXISTS (SELECT 1 FROM room_closures)
             OR EXISTS (SELECT 1 FROM rooms WHERE hours_confirmed)
          THEN RAISE EXCEPTION 'Refusing to discard populated room calendars';
          END IF;
        END $$;
    """)
    op.drop_table("room_closures")
    op.drop_table("room_exception_hours")
    op.drop_table("room_date_exceptions")
    op.drop_table("room_weekly_hours")
    op.drop_column("rooms", "hours_confirmed")
