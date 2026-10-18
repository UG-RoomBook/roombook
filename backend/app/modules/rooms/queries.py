"""Bounded room queries with set-based interval availability."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.bookings.models import Booking
from app.modules.rooms.models import Room
from app.modules.rooms.schemas import RoomAvailability, RoomList, RoomRead


def list_rooms(
    session: Session,
    *,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> RoomList:
    """List every room; interval availability is advisory until booking commits."""
    total = session.execute(select(func.count()).select_from(Room)).scalar_one()
    ordering = (Room.name.asc(), Room.id.asc())

    if starts_at is None or ends_at is None:
        rooms = session.scalars(select(Room).order_by(*ordering).limit(limit).offset(offset))
        items: list[RoomAvailability | RoomRead] = [RoomRead.model_validate(room) for room in rooms]
    else:
        overlap = (
            select(Booking.id)
            .where(
                Booking.room_id == Room.id,
                Booking.status == "active",
                Booking.starts_at < ends_at,
                Booking.ends_at > starts_at,
            )
            .correlate(Room)
            .exists()
        )
        rows = session.execute(
            select(Room, (Room.active.is_(True) & ~overlap).label("available"))
            .order_by(*ordering)
            .limit(limit)
            .offset(offset)
        )
        items = [
            RoomAvailability(**RoomRead.model_validate(room).model_dump(), available=available)
            for room, available in rows
        ]

    return RoomList(items=items, total=total, limit=limit, offset=offset)
