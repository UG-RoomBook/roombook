"""Create rooms and booking integrity constraints."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "rooms",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id", name="pk_rooms"),
        sa.UniqueConstraint("name", name="uq_rooms_name"),
        sa.CheckConstraint("capacity > 0", name=op.f("ck_rooms_positive_capacity")),
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("room_id", sa.UUID(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_bookings"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], name="fk_bookings_room_id_rooms"),
        sa.CheckConstraint("starts_at < ends_at", name=op.f("ck_bookings_valid_interval")),
        sa.CheckConstraint(
            "status IN ('active', 'cancelled')", name=op.f("ck_bookings_valid_status")
        ),
        sa.CheckConstraint(
            "(status = 'active' AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL)",
            name=op.f("ck_bookings_cancellation_state"),
        ),
        postgresql.ExcludeConstraint(
            ("room_id", "="),
            (sa.text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            where=sa.text("status = 'active'"),
            name="bookings_active_room_interval_excl",
            using="gist",
        ),
    )
    op.create_index("ix_bookings_starts_at_id", "bookings", ["starts_at", "id"])


def downgrade() -> None:
    op.drop_table("bookings")
    op.drop_table("rooms")
    # btree_gist may be shared by other database objects and remains installed.
