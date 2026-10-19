"""Add application identities, encrypted sessions and audit history without changing bookings."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(12), nullable=False, server_default="Member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "role IN ('Member', 'Admin')", name=op.f("ck_application_users_valid_role")
        ),
    )
    op.create_table(
        "external_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["application_users.id"]),
        sa.UniqueConstraint("issuer", "subject"),
        sa.UniqueConstraint("id", "user_id"),
        sa.CheckConstraint(
            "length(issuer) > 0 AND length(subject) > 0",
            name=op.f("ck_external_identities_nonempty_identity"),
        ),
    )
    op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("external_identity_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("provider_session_id", sa.String(36), nullable=False),
        sa.Column("aal", sa.String(4), nullable=False, server_default="aal1"),
        sa.Column("purpose", sa.String(12), nullable=False, server_default="standard"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_provider_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_owner", sa.UUID(), nullable=True),
        sa.Column("refresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["application_users.id"]),
        sa.ForeignKeyConstraint(
            ["external_identity_id", "user_id"],
            ["external_identities.id", "external_identities.user_id"],
        ),
        sa.UniqueConstraint("token_hash"),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_auth_sessions_valid_token_hash")
        ),
        sa.CheckConstraint("aal IN ('aal1', 'aal2')", name=op.f("ck_auth_sessions_valid_aal")),
        sa.CheckConstraint(
            "purpose IN ('standard', 'recovery')", name=op.f("ck_auth_sessions_valid_purpose")
        ),
        sa.CheckConstraint(
            "created_at < absolute_expires_at", name=op.f("ck_auth_sessions_valid_absolute_expiry")
        ),
        sa.CheckConstraint(
            "provider_session_id ~* "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name=op.f("ck_auth_sessions_valid_provider_session"),
        ),
        sa.CheckConstraint(
            "(refresh_owner IS NULL) = (refresh_until IS NULL)",
            name=op.f("ck_auth_sessions_paired_refresh_lease"),
        ),
    )
    op.create_index(
        "ix_auth_sessions_user_id_revoked_at", "auth_sessions", ["user_id", "revoked_at"]
    )
    op.create_index(
        "ix_auth_sessions_absolute_expires_at", "auth_sessions", ["absolute_expires_at"]
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["application_users.id"]),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'", name=op.f("ck_audit_events_details_object")
        ),
    )
    op.create_index("ix_audit_events_occurred_at_id", "audit_events", ["occurred_at", "id"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])


def downgrade() -> None:
    # Application rollback leaves this additive schema in place. An operator must
    # explicitly archive/remove identity data before attempting a destructive downgrade.
    # Lock before checking so a concurrent writer cannot insert between the guard and DROP.
    op.execute(
        "LOCK TABLE application_users, external_identities, auth_sessions, audit_events "
        "IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM application_users)
            OR EXISTS (SELECT 1 FROM external_identities)
            OR EXISTS (SELECT 1 FROM auth_sessions)
            OR EXISTS (SELECT 1 FROM audit_events) THEN
            RAISE EXCEPTION 'Identity tables contain data; retain additive schema on rollback';
        END IF;
        END $$"""
    )
    op.drop_table("audit_events")
    op.drop_table("auth_sessions")
    op.drop_table("external_identities")
    op.drop_table("application_users")
