"""Bounded room queries with set-based interval availability."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.availability.policy import validate_slot
from app.modules.availability.service import load_calendars
from app.modules.rooms.models import Room
from app.modules.rooms.schemas import RoomAvailability, RoomList, RoomRead


def list_rooms(
    session: Session,
    *,
    now: datetime,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> RoomList:
    """List every room; interval availability is advisory until booking commits."""
    slot = (
        validate_slot(starts_at, ends_at, now=now)
        if starts_at is not None and ends_at is not None
        else None
    )
    total = session.execute(select(func.count()).select_from(Room)).scalar_one()
    ordering = (Room.name.asc(), Room.id.asc())
    rooms = session.scalars(select(Room).order_by(*ordering).limit(limit).offset(offset)).all()
    if slot is None:
        items: list[RoomAvailability | RoomRead] = [RoomRead.model_validate(room) for room in rooms]
    else:
        calendars = load_calendars(session, rooms, starts_at=slot.starts_at, ends_at=slot.ends_at)
        items = [
            RoomAvailability(
                **RoomRead.model_validate(room).model_dump(),
                available=calendars[room.id].available(slot),
            )
            for room in rooms
        ]

    return RoomList(items=items, total=total, limit=limit, offset=offset)
