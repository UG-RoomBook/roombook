"""Additive administrator metadata and durable mutation receipts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rooms", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("application_users", sa.Column("verified_email", sa.String(320), nullable=True))
    op.add_column("application_users", sa.Column("email_checked_at", sa.DateTime(timezone=True)))
    op.add_column(
        "application_users", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column("auth_sessions", sa.Column("mfa_verified_at", sa.DateTime(timezone=True)))
    op.create_table(
        "admin_requests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("user_id", "key"),
        sa.ForeignKeyConstraint(["user_id"], ["application_users.id"]),
        sa.CheckConstraint("jsonb_typeof(result) = 'object'", name="result_object"),
    )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM admin_requests) THEN
        RAISE EXCEPTION 'Refusing to discard administrator retry history';
      END IF;
    END $$;""")
    op.drop_table("admin_requests")
    op.drop_column("auth_sessions", "mfa_verified_at")
    op.drop_column("application_users", "revision")
    op.drop_column("application_users", "email_checked_at")
    op.drop_column("application_users", "verified_email")
    op.drop_column("rooms", "revision")
