from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="valid_interval"),
        CheckConstraint("status IN ('active', 'cancelled')", name="valid_status"),
        CheckConstraint(
            "(status = 'active' AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL)",
            name="cancellation_state",
        ),
        ExcludeConstraint(
            ("room_id", "="),
            (func.tstzrange(text("starts_at"), text("ends_at"), "[)"), "&&"),
            where=text("status = 'active'"),
            name="bookings_active_room_interval_excl",
            using="gist",
        ),
        Index("ix_bookings_starts_at_id", "starts_at", "id"),
        Index("ix_bookings_owner_starts_at_id", "owner_id", "starts_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("application_users.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BookingRequest(Base):
    """Durable successful result. Keys never expire or get reused automatically."""

    __tablename__ = "booking_requests"
    __table_args__ = (CheckConstraint("jsonb_typeof(result) = 'object'", name="result_object"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("application_users.id"), primary_key=True)
    key: Mapped[UUID] = mapped_column(primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"), unique=True, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
