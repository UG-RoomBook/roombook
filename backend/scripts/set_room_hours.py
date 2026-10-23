"""Operator command: confirm weekly opening hours for rooms.

RB-51 keeps every room unavailable until its real hours are confirmed through a
reviewed operator process. This is that process for Staging and Production:
it replaces a room's weekly windows and marks its hours confirmed, inside the
same row lock bookings use, so a change that would leave an active or future
booking outside the new hours is rejected (BOOKINGS_AFFECTED) and nothing is
written. Date exceptions and closures are left untouched.

Without --confirm it only prints what it would do.

    python -m scripts.set_room_hours --days mon-fri --opens 09:00 --closes 17:00 --confirm
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.db.session import Database
from app.modules.availability.models import WeeklyHours
from app.modules.availability.policy import current_time
from app.modules.availability.service import locked_room
from app.modules.rooms.models import Room
from scripts.seed_rooms import ROOMS

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
REFERENCE_ROOM_IDS: tuple[UUID, ...] = tuple(room["id"] for room in ROOMS)


def parse_days(value: str) -> tuple[int, ...]:
    """'mon-fri', 'sat,sun' or 'all' to Monday = 0 ... Sunday = 6."""
    text = value.strip().lower()
    if text == "all":
        return tuple(range(7))
    days: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            first, last = (piece.strip() for piece in part.split("-", 1))
            if first not in DAY_NAMES or last not in DAY_NAMES:
                raise ValueError(f"Unknown day range: {part!r}")
            start, end = DAY_NAMES.index(first), DAY_NAMES.index(last)
            if start > end:
                raise ValueError(f"Day range must run Monday to Sunday: {part!r}")
            days.update(range(start, end + 1))
        elif part in DAY_NAMES:
            days.add(DAY_NAMES.index(part))
        else:
            raise ValueError(f"Unknown day: {part!r}")
    return tuple(sorted(days))


def parse_minute(value: str) -> int:
    """'HH:MM' on a 15-minute boundary to minutes from local midnight (24:00 allowed)."""
    try:
        hours, minutes = (int(piece) for piece in value.split(":"))
    except ValueError:
        raise ValueError(f"Time must be HH:MM: {value!r}") from None
    total = hours * 60 + minutes
    if not 0 <= minutes < 60 or not 0 <= total <= 1440 or total % 15:
        raise ValueError(f"Time must be 00:00-24:00 on a 15-minute boundary: {value!r}")
    return total


def describe(days: Sequence[int], start_minute: int, end_minute: int) -> str:
    def clock(minute: int) -> str:
        return f"{minute // 60:02}:{minute % 60:02}"

    names = ",".join(DAY_NAMES[day] for day in days)
    return f"{names} {clock(start_minute)}-{clock(end_minute)}"


def set_weekly_hours(
    session: Session,
    room_id: UUID,
    days: Sequence[int],
    start_minute: int,
    end_minute: int,
    *,
    clock: Callable[[], datetime] = current_time,
) -> bool:
    """Replace one room's weekly hours and confirm them. True if anything changed.

    Owns its transaction through locked_room: pass a clean session.
    """
    if not days or not 0 <= start_minute < end_minute <= 1440:
        raise ValueError("Opening hours need at least one day and opens < closes")
    wanted = sorted((day, start_minute, end_minute) for day in days)
    with locked_room(session, room_id, clock=clock) as guard:
        current = sorted(
            (row.weekday, row.start_minute, row.end_minute)
            for row in session.scalars(select(WeeklyHours).where(WeeklyHours.room_id == room_id))
        )
        if current == wanted and guard.room.hours_confirmed:
            return False
        session.execute(delete(WeeklyHours).where(WeeklyHours.room_id == room_id))
        session.add_all(
            WeeklyHours(room_id=room_id, weekday=day, start_minute=start, end_minute=end)
            for day, start, end in wanted
        )
        guard.room.hours_confirmed = True
        guard.room.revision += 1
        # locked_room's exit check rejects the change if it strands a booking.
    return True


def resolve_rooms(session: Session, selectors: Sequence[str]) -> list[Room]:
    if not selectors:
        rooms = list(session.scalars(select(Room).where(Room.id.in_(REFERENCE_ROOM_IDS))))
        if len(rooms) != len(REFERENCE_ROOM_IDS):
            raise ValueError("Reference rooms are missing; run scripts.seed_rooms first")
        return sorted(rooms, key=lambda room: room.name)
    rooms = []
    for selector in selectors:
        try:
            room = session.get(Room, UUID(selector))
        except ValueError:
            room = session.scalar(select(Room).where(Room.name == selector))
        if room is None:
            raise ValueError(f"No room matches {selector!r}")
        rooms.append(room)
    return rooms


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", default="mon-fri", help="e.g. mon-fri, sat,sun or all")
    parser.add_argument("--opens", default="09:00", help="local Melbourne time, HH:MM")
    parser.add_argument("--closes", default="17:00", help="local Melbourne time, HH:MM")
    parser.add_argument(
        "--room",
        action="append",
        default=[],
        help="room name or ID; repeatable (default: the two reference rooms)",
    )
    parser.add_argument("--confirm", action="store_true", help="write the change")
    args = parser.parse_args(argv)
    try:
        days = parse_days(args.days)
        start_minute, end_minute = parse_minute(args.opens), parse_minute(args.closes)
        if start_minute >= end_minute:
            raise ValueError("--opens must be before --closes")
    except ValueError as error:
        parser.error(str(error))

    settings = Settings()
    database = Database(settings.database_url)
    hours = describe(days, start_minute, end_minute)
    failed = False
    try:
        with database.session() as session:
            rooms = [(room.id, room.name) for room in resolve_rooms(session, args.room)]
        for room_id, name in rooms:
            if not args.confirm:
                print(json.dumps({"room": name, "hours": hours, "result": "dry run"}))
                continue
            try:
                with database.session() as session:
                    changed = set_weekly_hours(session, room_id, days, start_minute, end_minute)
                result = "set" if changed else "unchanged"
            except ApiError as error:
                failed, result = True, f"rejected: {error.code}"
            print(json.dumps({"room": name, "hours": hours, "result": result}))
    finally:
        database.dispose()
    if not args.confirm:
        print("Dry run only; add --confirm to write.", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
