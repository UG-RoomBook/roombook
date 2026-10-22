from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.availability.models import WeeklyHours
from app.modules.availability.policy import Interval
from app.modules.availability.service import load_calendars
from app.modules.bookings.models import Booking
from app.modules.rooms.models import Room
from scripts import set_room_hours
from scripts.seed_rooms import seed_rooms
from scripts.set_room_hours import (
    REFERENCE_ROOM_IDS,
    parse_days,
    parse_minute,
    set_weekly_hours,
)

pytestmark = pytest.mark.database

# Monday 2026-10-26 in Melbourne (AEDT, UTC+11). The clock is the Friday before.
MONDAY_10_LOCAL = datetime(2026, 10, 25, 23, 0, tzinfo=UTC)
SATURDAY_10_LOCAL = datetime(2026, 10, 30, 23, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)


def clock() -> datetime:
    return NOW


def seeded(db_engine: Engine) -> None:
    with Session(db_engine) as session, session.begin():
        seed_rooms(session)


def windows(db_engine: Engine) -> dict[str, list[tuple[int, int, int]]]:
    with Session(db_engine) as session:
        rooms = session.scalars(select(Room).where(Room.id.in_(REFERENCE_ROOM_IDS))).all()
        return {
            room.name: sorted(
                (row.weekday, row.start_minute, row.end_minute)
                for row in session.scalars(
                    select(WeeklyHours).where(WeeklyHours.room_id == room.id)
                )
            )
            for room in rooms
        }


def available(db_engine: Engine, starts_at: datetime) -> bool:
    with Session(db_engine) as session:
        room = session.get(Room, REFERENCE_ROOM_IDS[0])
        assert room is not None
        slot = Interval(starts_at, starts_at + timedelta(hours=1))
        calendar = load_calendars(session, [room], starts_at=slot.starts_at, ends_at=slot.ends_at)
        return calendar[room.id].available(slot)


def test_parsing_accepts_operator_formats_and_rejects_mistakes() -> None:
    assert parse_days("mon-fri") == (0, 1, 2, 3, 4)
    assert parse_days("sat, sun") == (5, 6)
    assert parse_days("ALL") == tuple(range(7))
    assert parse_minute("09:00") == 540 and parse_minute("24:00") == 1440
    for bad in ("fri-mon", "funday", "mon-xyz"):
        with pytest.raises(ValueError):
            parse_days(bad)
    for bad in ("9", "09:10", "25:00", "09:60"):
        with pytest.raises(ValueError):
            parse_minute(bad)


def test_confirms_hours_and_opens_rooms_only_within_them(
    db_engine: Engine, clean_database: None
) -> None:
    seeded(db_engine)
    assert not available(db_engine, MONDAY_10_LOCAL)  # unconfirmed rooms never open

    for room_id in REFERENCE_ROOM_IDS:
        with Session(db_engine) as session:
            assert set_weekly_hours(session, room_id, (0, 1, 2, 3, 4), 540, 1020, clock=clock)

    weekday_hours = [(day, 540, 1020) for day in range(5)]
    assert windows(db_engine) == {"The Studio": weekday_hours, "The Forum": weekday_hours}
    with Session(db_engine) as session:
        assert all(room.hours_confirmed for room in session.scalars(select(Room)))
    assert available(db_engine, MONDAY_10_LOCAL)
    assert not available(db_engine, SATURDAY_10_LOCAL)

    # Running it again is a no-op.
    with Session(db_engine) as session:
        assert not set_weekly_hours(
            session, REFERENCE_ROOM_IDS[0], range(5), 540, 1020, clock=clock
        )


def test_change_that_strands_a_future_booking_is_rejected_and_rolled_back(
    db_engine: Engine, clean_database: None
) -> None:
    seeded(db_engine)
    room_id = REFERENCE_ROOM_IDS[0]
    with Session(db_engine) as session:
        set_weekly_hours(session, room_id, range(5), 540, 1020, clock=clock)
    with Session(db_engine) as session, session.begin():
        session.add(
            Booking(
                room_id=room_id,
                starts_at=MONDAY_10_LOCAL,
                ends_at=MONDAY_10_LOCAL + timedelta(hours=1),
            )
        )

    # Afternoons only would leave the Monday 10:00 booking outside opening hours.
    with Session(db_engine) as session, pytest.raises(ApiError) as rejected:
        set_weekly_hours(session, room_id, range(5), 780, 1020, clock=clock)
    assert rejected.value.code == "BOOKINGS_AFFECTED"
    assert windows(db_engine)["The Studio"] == [(day, 540, 1020) for day in range(5)]


def test_command_is_a_dry_run_unless_confirmed(
    db_engine: Engine, database_url: str, clean_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    seeded(db_engine)
    with patch.dict("os.environ", {"ROOMBOOK_DATABASE_URL": database_url}):
        assert set_room_hours.main([]) == 0
        assert windows(db_engine) == {"The Studio": [], "The Forum": []}
        assert '"result": "dry run"' in capsys.readouterr().out

        assert set_room_hours.main(["--confirm", "--room", "The Forum"]) == 0
        assert '"result": "set"' in capsys.readouterr().out
        assert windows(db_engine)["The Forum"] == [(day, 540, 1020) for day in range(5)]
        assert windows(db_engine)["The Studio"] == []
