"""Public, bounded room-day choices evaluated by the shared booking policy."""

from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.availability.policy import (
    CAMPUS,
    HORIZON,
    local_instant,
    utc,
    validate_slot,
)
from app.modules.availability.service import load_calendars
from app.modules.rooms.models import Room
from app.modules.rooms.schemas import (
    RoomAvailability,
    RoomDayAvailability,
    RoomEndChoice,
    RoomRead,
    RoomStartChoice,
)


def find_room(session: Session, room_id: UUID) -> Room:
    room = session.scalar(select(Room).where(Room.id == room_id))
    if room is None:
        raise ApiError(404, "ROOM_NOT_FOUND", "The room was not found.")
    return room


def read_room(
    session: Session,
    room_id: UUID,
    *,
    now: datetime,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> RoomRead | RoomAvailability:
    room = find_room(session, room_id)
    if starts_at is None or ends_at is None:
        return RoomRead.model_validate(room)
    interval = validate_slot(starts_at, ends_at, now=now)
    calendar = load_calendars(
        session,
        [room],
        starts_at=interval.starts_at,
        ends_at=interval.ends_at,
    )[room.id]
    return RoomAvailability(
        **RoomRead.model_validate(room).model_dump(),
        available=calendar.available(interval),
    )


def room_day(
    session: Session,
    room_id: UUID,
    *,
    day: date,
    now: datetime,
) -> RoomDayAvailability:
    clock = utc(now)
    horizon = clock + HORIZON
    if not clock.astimezone(CAMPUS).date() <= day <= horizon.astimezone(CAMPUS).date():
        raise ApiError(422, "VALIDATION_ERROR", "Choose a date from today through 14 days ahead.")
    room = find_room(session, room_id)
    midnight = datetime.combine(day, time())
    calendar = load_calendars(
        session,
        [room],
        starts_at=local_instant(midnight),
        ends_at=local_instant(midnight + timedelta(days=1)),
    )[room.id]
    choices: list[RoomStartChoice] = []
    for minute in range(0, 1440, 15):
        wall_time = midnight + timedelta(minutes=minute)
        choice = RoomStartChoice(
            time=wall_time.strftime("%H:%M"),
            starts_at=None,
            available=False,
            unavailable_reason="unavailable",
            valid_ends=[],
        )
        choices.append(choice)
        try:
            start = local_instant(wall_time)
        except ApiError:
            choice.unavailable_reason = "invalid_local_time"
            continue
        choice.starts_at = start
        if not room.active:
            choice.unavailable_reason = "inactive"
        elif not room.hours_confirmed:
            choice.unavailable_reason = "schedule_unconfirmed"
        elif start <= clock:
            choice.unavailable_reason = "past"
        elif start > horizon:
            choice.unavailable_reason = "outside_horizon"
        else:
            for duration in range(30, 121, 15):
                end = start + timedelta(minutes=duration)
                local_end = end.astimezone(CAMPUS)
                if local_end.date() != day:
                    continue
                try:
                    interval = validate_slot(start, end, now=clock)
                except ApiError:
                    continue
                if calendar.available(interval):
                    choice.valid_ends.append(
                        RoomEndChoice(time=local_end.strftime("%H:%M"), ends_at=end)
                    )
            choice.available = bool(choice.valid_ends)
            if choice.available:
                choice.unavailable_reason = None
    return RoomDayAvailability(
        room=RoomRead.model_validate(room),
        date=day,
        generated_at=clock,
        booking_window_ends_at=horizon,
        slots=choices,
    )
