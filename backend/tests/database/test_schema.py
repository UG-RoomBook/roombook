import os
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from psycopg.errors import ExclusionViolation
from sqlalchemy import DateTime, Engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.modules.bookings.models import Booking
from app.modules.rooms.models import Room
from scripts.seed_rooms import ROOMS, seed_rooms

pytestmark = pytest.mark.database
START = datetime(2026, 10, 19, 2, tzinfo=UTC)


def add_room(session: Session) -> Room:
    room = Room(name="Test room", location="Test building", capacity=4)
    session.add(room)
    session.flush()
    return room


def booking(room_id: UUID, **values: object) -> Booking:
    data: dict[str, object] = {
        "room_id": room_id,
        "starts_at": START,
        "ends_at": START + timedelta(hours=1),
        "status": "active",
    }
    data.update(values)
    return Booking(**data)


def test_migrations_round_trip_and_repeated_upgrade(
    database_url: str, db_engine: Engine, clean_database: None
) -> None:
    with patch.dict(os.environ, {"ROOMBOOK_DATABASE_URL": database_url}):
        config = Config("alembic.ini")
        command.downgrade(config, "base")
        assert "rooms" not in inspect(db_engine).get_table_names()
        assert "bookings" not in inspect(db_engine).get_table_names()
        command.upgrade(config, "head")
        command.upgrade(config, "head")
    schema = inspect(db_engine)
    assert {"rooms", "bookings"} <= set(schema.get_table_names())
    columns = {column["name"]: column for column in schema.get_columns("bookings")}
    for name in ("starts_at", "ends_at"):
        column_type = columns[name]["type"]
        assert isinstance(column_type, DateTime)
        assert column_type.timezone is True


def test_room_seed_is_idempotent_and_contains_no_bookings(db_session: Session) -> None:
    assert seed_rooms(db_session) == 2
    assert seed_rooms(db_session) == 0
    rooms = db_session.scalars(select(Room).order_by(Room.id)).all()
    assert [(r.id, r.name, r.location, r.capacity) for r in rooms] == [
        (r["id"], r["name"], r["location"], r["capacity"]) for r in ROOMS
    ]
    assert db_session.scalar(select(func.count()).select_from(Booking)) == 0
    rooms[0].capacity = 6
    db_session.flush()
    assert seed_rooms(db_session) == 0
    stored_room = db_session.get(Room, rooms[0].id)
    assert stored_room is not None
    assert stored_room.capacity == 6


@pytest.mark.parametrize("capacity", [0, -1])
def test_database_rejects_nonpositive_room_capacity(db_session: Session, capacity: int) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(Room(name="Invalid", location="Test", capacity=capacity))
        db_session.flush()


def test_database_rejects_duplicate_room_names(db_session: Session) -> None:
    room = add_room(db_session)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(Room(name=room.name, location="Elsewhere", capacity=8))
        db_session.flush()


def test_database_rejects_orphan_bookings(db_session: Session) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(booking(uuid4()))
        db_session.flush()


@pytest.mark.parametrize(
    "changes",
    [
        {"ends_at": START},
        {"ends_at": START - timedelta(minutes=1)},
        {"status": "unknown"},
        {"status": "cancelled", "cancelled_at": None},
        {"status": "active", "cancelled_at": START},
    ],
)
def test_database_rejects_invalid_booking_state(
    db_session: Session, changes: dict[str, object]
) -> None:
    room = add_room(db_session)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(booking(room.id, **changes))
        db_session.flush()


def test_active_overlap_is_rejected_by_named_constraint(db_session: Session) -> None:
    room = add_room(db_session)
    db_session.add(booking(room.id))
    db_session.flush()
    with pytest.raises(IntegrityError) as caught, db_session.begin_nested():
        db_session.add(booking(room.id, starts_at=START + timedelta(minutes=30)))
        db_session.flush()
    assert isinstance(caught.value.orig, ExclusionViolation)
    assert caught.value.orig.diag.constraint_name == "bookings_active_room_interval_excl"


def test_adjacent_and_cancelled_intervals_do_not_conflict(db_session: Session) -> None:
    room = add_room(db_session)
    db_session.add_all(
        [
            booking(room.id),
            booking(
                room.id,
                starts_at=START + timedelta(hours=1),
                ends_at=START + timedelta(hours=2),
            ),
            booking(room.id, status="cancelled", cancelled_at=START),
        ]
    )
    db_session.flush()
    assert db_session.scalar(select(func.count()).select_from(Booking)) == 3


def test_equivalent_timezone_offsets_are_same_instant(db_session: Session) -> None:
    room = add_room(db_session)
    offset = timezone(timedelta(hours=11))
    item = booking(
        room.id,
        starts_at=START.astimezone(offset),
        ends_at=(START + timedelta(hours=1)).astimezone(offset),
    )
    db_session.add(item)
    db_session.flush()
    db_session.refresh(item)
    assert item.starts_at == START
    assert item.starts_at.utcoffset() == timedelta(0)
