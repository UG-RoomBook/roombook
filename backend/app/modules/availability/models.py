from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WeeklyHours(Base):
    __tablename__ = "room_weekly_hours"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="valid_weekday"),
        CheckConstraint(
            "0 <= start_minute AND start_minute < end_minute AND end_minute <= 1440",
            name="valid_minutes",
        ),
        ExcludeConstraint(
            ("room_id", "="),
            ("weekday", "="),
            (func.int4range(text("start_minute"), text("end_minute"), "[)"), "&&"),
            name="room_weekly_hours_interval_excl",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    weekday: Mapped[int]
    start_minute: Mapped[int]
    end_minute: Mapped[int]


class DateException(Base):
    """Replaces the entire local day's weekly hours; zero windows means closed."""

    __tablename__ = "room_date_exceptions"
    __table_args__ = (UniqueConstraint("room_id", "date"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)


class ExceptionHours(Base):
    __tablename__ = "room_exception_hours"
    __table_args__ = (
        CheckConstraint(
            "0 <= start_minute AND start_minute < end_minute AND end_minute <= 1440",
            name="valid_minutes",
        ),
        ExcludeConstraint(
            ("exception_id", "="),
            (func.int4range(text("start_minute"), text("end_minute"), "[)"), "&&"),
            name="room_exception_hours_interval_excl",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    exception_id: Mapped[UUID] = mapped_column(
        ForeignKey("room_date_exceptions.id", ondelete="CASCADE"), nullable=False
    )
    start_minute: Mapped[int]
    end_minute: Mapped[int]


class Closure(Base):
    __tablename__ = "room_closures"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="valid_interval"),
        CheckConstraint("length(trim(reason)) > 0", name="nonempty_reason"),
        Index("ix_room_closures_room_id_starts_at", "room_id", "starts_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
