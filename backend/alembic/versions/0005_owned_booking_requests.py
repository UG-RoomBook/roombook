"""Preserve unowned history and add atomic owned-booking retry records."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_bookings_owner_id_application_users"),
        "bookings",
        "application_users",
        ["owner_id"],
        ["id"],
    )
    op.create_index("ix_bookings_owner_starts_at_id", "bookings", ["owner_id", "starts_at", "id"])
    op.create_table(
        "booking_requests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_id", "key"),
        sa.ForeignKeyConstraint(["user_id"], ["application_users.id"]),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.UniqueConstraint("booking_id"),
        sa.CheckConstraint("jsonb_typeof(result) = 'object'", name="result_object"),
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM bookings WHERE owner_id IS NOT NULL)
             OR EXISTS (SELECT 1 FROM booking_requests)
          THEN RAISE EXCEPTION 'Refusing to discard booking ownership or retry history';
          END IF;
        END $$;
    """)
    op.drop_table("booking_requests")
    op.drop_index("ix_bookings_owner_starts_at_id", table_name="bookings")
    op.drop_constraint(
        op.f("fk_bookings_owner_id_application_users"), "bookings", type_="foreignkey"
    )
    op.drop_column("bookings", "owner_id")
