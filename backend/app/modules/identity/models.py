"""Application-owned identities and opaque sessions; provider credentials stay encrypted."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApplicationUser(Base):
    __tablename__ = "application_users"
    __table_args__ = (CheckConstraint("role IN ('Member', 'Admin')", name="valid_role"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    role: Mapped[str] = mapped_column(String(12), nullable=False, server_default="Member")
    verified_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject"),
        UniqueConstraint("id", "user_id"),
        CheckConstraint("length(issuer) > 0 AND length(subject) > 0", name="nonempty_identity"),
        Index("ix_external_identities_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("application_users.id"), nullable=False)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["external_identity_id", "user_id"],
            ["external_identities.id", "external_identities.user_id"],
        ),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="valid_token_hash"),
        CheckConstraint("aal IN ('aal1', 'aal2')", name="valid_aal"),
        CheckConstraint("purpose IN ('standard', 'recovery')", name="valid_purpose"),
        CheckConstraint("created_at < absolute_expires_at", name="valid_absolute_expiry"),
        CheckConstraint(
            "provider_session_id ~* "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name="valid_provider_session",
        ),
        CheckConstraint(
            "(refresh_owner IS NULL) = (refresh_until IS NULL)", name="paired_refresh_lease"
        ),
        Index("ix_auth_sessions_user_id_revoked_at", "user_id", "revoked_at"),
        Index("ix_auth_sessions_absolute_expires_at", "absolute_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("application_users.id"), nullable=False)
    external_identity_id: Mapped[UUID] = mapped_column(nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    access_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    provider_session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    aal: Mapped[str] = mapped_column(String(4), nullable=False, server_default="aal1")
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str] = mapped_column(String(12), nullable=False, server_default="standard")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_provider_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_owner: Mapped[UUID | None] = mapped_column(nullable=True)
    refresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_object"),
        Index("ix_audit_events_occurred_at_id", "occurred_at", "id"),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("application_users.id"), nullable=True
    )
    target_id: Mapped[UUID | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
