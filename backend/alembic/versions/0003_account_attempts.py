"""Add shared, keyed account abuse counters without changing user or booking data."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_attempts",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", "bucket"),
    )
    op.create_index("ix_account_attempts_bucket", "account_attempts", ["bucket"])


def downgrade() -> None:
    op.drop_table("account_attempts")
