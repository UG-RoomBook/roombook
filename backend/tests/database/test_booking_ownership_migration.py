import os
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command
from app.modules.bookings.models import Booking, BookingRequest
from app.modules.bookings.schemas import BookingCreate
from app.modules.bookings.service import create_booking
from app.modules.identity.models import ApplicationUser
from scripts.inventory_legacy_bookings import inventory_legacy_bookings
from tests.availability.test_service import END, NOW, START, add_room

pytestmark = pytest.mark.database


def test_upgrade_preserves_unowned_history_and_empty_downgrade(
    db_engine: Engine, database_url: str, clean_database: None
) -> None:
    room, booking = uuid4(), uuid4()
    with patch.dict(os.environ, {"ROOMBOOK_DATABASE_URL": database_url}):
        config = Config("alembic.ini")
        command.downgrade(config, "0004")
        with db_engine.begin() as connection:
            connection.execute(
                text("INSERT INTO rooms(id,name,location,capacity) VALUES (:id,'Legacy','Test',4)"),
                {"id": room},
            )
            connection.execute(
                text(
                    "INSERT INTO bookings(id,room_id,starts_at,ends_at) "
                    "VALUES (:id,:room,:start,:end)"
                ),
                {"id": booking, "room": room, "start": START, "end": END},
            )
            original = connection.execute(text("SELECT * FROM bookings")).one()
        with Session(db_engine) as session:
            assert inventory_legacy_bookings(session)["total"] == 1
        command.upgrade(config, "head")
        with Session(db_engine) as session:
            record = session.get(Booking, booking)
            assert record is not None and record.owner_id is None
            assert record.room_id == room and record.starts_at == START and record.ends_at == END
            assert inventory_legacy_bookings(session)["total"] == 1
        command.downgrade(config, "0004")
        with db_engine.connect() as connection:
            assert connection.execute(text("SELECT * FROM bookings")).one() == original
        command.upgrade(config, "head")


def test_populated_ownership_and_retry_history_cannot_be_discarded(
    db_engine: Engine, database_url: str, clean_database: None
) -> None:
    user = uuid4()
    with Session(db_engine) as session, session.begin():
        session.add(ApplicationUser(id=user))
        room_id = add_room(session).id
    with Session(db_engine) as session:
        result = create_booking(
            session,
            user_id=user,
            key=uuid4(),
            body=BookingCreate(room_id=room_id, starts_at=START, ends_at=END),
            clock=lambda: NOW,
        )
    with patch.dict(os.environ, {"ROOMBOOK_DATABASE_URL": database_url}):
        with pytest.raises(DBAPIError, match="Refusing to discard booking"):
            command.downgrade(Config("alembic.ini"), "0004")
    with Session(db_engine) as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0005"
        assert session.scalars(select(BookingRequest)).one().booking_id == result.id
        assert inventory_legacy_bookings(session)["total"] == 0
