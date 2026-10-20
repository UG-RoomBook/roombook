import os
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings
from app.modules.availability.models import WeeklyHours
from app.modules.rooms.models import Room
from scripts.inventory_calendars import inventory
from scripts.seed_synthetic_calendar import SYNTHETIC_ROOM_ID, seed_synthetic_calendar

pytestmark = pytest.mark.database


def test_prior_schema_data_survives_upgrade_and_empty_calendar_downgrade(
    db_engine: Engine, database_url: str, clean_database: None
) -> None:
    room_id, booking_id = uuid4(), uuid4()
    with patch.dict(os.environ, {"ROOMBOOK_DATABASE_URL": database_url}):
        config = Config("alembic.ini")
        command.downgrade(config, "0003")
        with db_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO rooms(id,name,location,capacity) "
                    "VALUES (:id,'Prior room','Test',4)"
                ),
                {"id": room_id},
            )
            connection.execute(
                text(
                    "INSERT INTO bookings(id,room_id,starts_at,ends_at) "
                    "VALUES (:id,:room,'2026-10-19T02:00Z','2026-10-19T03:00Z')"
                ),
                {"id": booking_id, "room": room_id},
            )
            before = connection.execute(text("SELECT * FROM bookings")).all()
        command.upgrade(config, "head")
        with Session(db_engine) as session:
            room = session.get(Room, room_id)
            assert room is not None and room.hours_confirmed is False
            assert inventory(session)["rooms_without_confirmed_hours"] == 1
            assert session.execute(text("SELECT * FROM bookings")).all() == before
        command.downgrade(config, "0003")
        with db_engine.connect() as connection:
            assert connection.execute(text("SELECT * FROM bookings")).all() == before
            assert connection.scalar(text("SELECT id FROM rooms")) == room_id
        command.upgrade(config, "head")


def test_populated_calendars_refuse_destructive_downgrade(
    db_engine: Engine, database_url: str, clean_database: None
) -> None:
    settings = Settings(database_url=database_url, environment="test")
    with Session(db_engine) as session, session.begin():
        assert seed_synthetic_calendar(session, settings)
    with patch.dict(os.environ, {"ROOMBOOK_DATABASE_URL": database_url}):
        with pytest.raises(DBAPIError, match="Refusing to discard"):
            command.downgrade(Config("alembic.ini"), "0003")
    with Session(db_engine) as session:
        assert inventory(session)["revision"] == "0004"
        assert len(session.scalars(select(WeeklyHours)).all()) == 7


def test_synthetic_seed_never_overwrites_edits(db_session: Session, database_url: str) -> None:
    settings = Settings(database_url=database_url, environment="test")
    assert seed_synthetic_calendar(db_session, settings)
    room = db_session.get(Room, SYNTHETIC_ROOM_ID)
    assert room is not None
    room.active, room.hours_confirmed = False, False
    hours = db_session.scalars(select(WeeklyHours)).first()
    assert hours is not None
    hours.end_minute = 900
    db_session.flush()
    assert not seed_synthetic_calendar(db_session, settings)
    assert room.active is False and room.hours_confirmed is False and hours.end_minute == 900


@pytest.mark.parametrize(
    ("environment", "url"),
    [
        ("production", "postgresql+psycopg://localhost/db"),
        ("test", "postgresql+psycopg://remote/db"),
        ("development", None),
    ],
)
def test_synthetic_seed_refuses_other_environments(
    db_session: Session, environment: str, url: str | None
) -> None:
    with pytest.raises(ValueError, match="localhost"):
        seed_synthetic_calendar(db_session, Settings(environment=environment, database_url=url))
