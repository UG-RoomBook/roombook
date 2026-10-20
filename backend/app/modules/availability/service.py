"""Set-based reads and the common transaction for booking/schedule writers."""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, SessionTransaction

from app.core.errors import ApiError
from app.modules.availability.models import Closure, DateException, ExceptionHours, WeeklyHours
from app.modules.availability.policy import (
    CAMPUS,
    HORIZON,
    MAX_DURATION,
    Calendar,
    Hours,
    Interval,
    current_time,
    next_slot,
    utc,
    validate_duration,
    validate_slot,
)
from app.modules.bookings.models import Booking
from app.modules.rooms.models import Room


def load_calendars(
    session: Session, rooms: Sequence[Room], *, starts_at: datetime, ends_at: datetime
) -> dict[UUID, Calendar]:
    """Four reads for up to 100 rooms; no per-room or per-candidate queries."""
    if len(rooms) > 100:
        raise ValueError("Load at most 100 room calendars per page")
    calendars = {
        room.id: Calendar(room.active, room.hours_confirmed, {}, {}, [], []) for room in rooms
    }
    if not calendars:
        return calendars
    ids = list(calendars)
    for hours in session.scalars(select(WeeklyHours).where(WeeklyHours.room_id.in_(ids))):
        calendars[hours.room_id].weekly.setdefault(hours.weekday, []).append(
            Hours(hours.start_minute, hours.end_minute)
        )
    for exception, window in session.execute(
        select(DateException, ExceptionHours)
        .outerjoin(ExceptionHours, ExceptionHours.exception_id == DateException.id)
        .where(
            DateException.room_id.in_(ids),
            DateException.date >= starts_at.astimezone(CAMPUS).date(),
            DateException.date <= ends_at.astimezone(CAMPUS).date(),
        )
    ):
        windows = calendars[exception.room_id].exceptions.setdefault(exception.date, [])
        if window is not None:
            windows.append(Hours(window.start_minute, window.end_minute))
    for closure in session.scalars(
        select(Closure).where(
            Closure.room_id.in_(ids), Closure.starts_at < ends_at, Closure.ends_at > starts_at
        )
    ):
        calendars[closure.room_id].closures.append(Interval(closure.starts_at, closure.ends_at))
    for booking in session.scalars(
        select(Booking).where(
            Booking.room_id.in_(ids),
            Booking.status == "active",
            Booking.starts_at < ends_at,
            Booking.ends_at > starts_at,
        )
    ):
        calendars[booking.room_id].bookings.append(Interval(booking.starts_at, booking.ends_at))
    return calendars


def next_slots(
    session: Session,
    rooms: Sequence[Room],
    *,
    duration: timedelta,
    now: datetime,
    not_before: datetime | None = None,
) -> dict[UUID, Interval | None]:
    """Internal foundation for RB-54; callers supply one bounded room page."""
    validate_duration(duration)
    clock = utc(now)
    calendars = load_calendars(
        session, rooms, starts_at=clock, ends_at=clock + HORIZON + MAX_DURATION
    )
    return {
        room_id: next_slot(calendar, duration=duration, now=clock, not_before=not_before)
        for room_id, calendar in calendars.items()
    }


class LockedRoom:
    """Only valid within locked_room; never cache this guard or commit inside it."""

    def __init__(
        self,
        session: Session,
        room: Room,
        transaction: SessionTransaction,
        clock: Callable[[], datetime],
    ) -> None:
        self.session = session
        self.room = room
        self.transaction = transaction
        self.clock = clock

    def _check_transaction(self) -> None:
        if not self.transaction.is_active or self.session.get_transaction() is not self.transaction:
            raise RuntimeError("The room lock must be used within its original transaction")

    def require_available(self, starts_at: datetime, ends_at: datetime) -> Interval:
        """Recheck after acquiring the row lock, immediately before booking insert."""
        self._check_transaction()
        slot = validate_slot(starts_at, ends_at, now=self.clock())
        calendar = load_calendars(
            self.session, [self.room], starts_at=slot.starts_at, ends_at=slot.ends_at
        )[self.room.id]
        if not calendar.available(slot):
            raise ApiError(409, "ROOM_UNAVAILABLE", "The room is unavailable for this interval.")
        return slot

    def preserve_bookings(self) -> None:
        """Reject availability mutations affecting ongoing/future reservations.

        Policy changes do not retroactively invalidate a legacy reservation's
        duration, lead time, alignment or DST endpoint. Calendar support does.
        """
        self._check_transaction()
        self.session.flush()
        bookings = self.session.scalars(
            select(Booking).where(
                Booking.room_id == self.room.id,
                Booking.status == "active",
                Booking.ends_at > self.clock(),
            )
        ).all()
        if not bookings:
            return
        calendar = load_calendars(
            self.session,
            [self.room],
            starts_at=min(booking.starts_at for booking in bookings),
            ends_at=max(booking.ends_at for booking in bookings),
        )[self.room.id]
        if any(
            not calendar.supports(Interval(booking.starts_at, booking.ends_at))
            for booking in bookings
        ):
            raise ApiError(
                409,
                "BOOKINGS_AFFECTED",
                "Resolve affected active bookings explicitly before changing availability.",
            )


@contextmanager
def locked_room(
    session: Session, room_id: UUID, *, clock: Callable[[], datetime] = current_time
) -> Iterator[LockedRoom]:
    """Own one READ COMMITTED transaction and lock before any availability write.

    Booking (RB-15) and admin (RB-52/53) must use this helper, including their
    authorization, idempotency and audit writes. No commit/rollback inside the
    block. The caller closes the session. A failure rolls the entire block back.
    """
    if session.in_transaction() or session.new or session.dirty or session.deleted:
        raise RuntimeError("Use a clean session; locked_room owns the transaction")
    with session.begin() as transaction:
        if session.connection().get_isolation_level() != "READ COMMITTED":
            raise RuntimeError("Room writers require READ COMMITTED isolation")
        room = session.scalar(
            select(Room)
            .where(Room.id == room_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if room is None:
            raise ApiError(404, "ROOM_NOT_FOUND", "The room was not found.")
        guard = LockedRoom(session, room, transaction, clock)
        yield guard
        guard.preserve_bookings()
