import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command
from app.modules.availability.models import Closure, DateException, ExceptionHours
from app.modules.bookings.models import Booking
from app.modules.rooms.models import Room
from tests.admin.conftest import headers
from tests.admin.test_workspace import create
from tests.admin_provider import AdminProvider

pytestmark = pytest.mark.database


def test_schedule_roundtrip_overrides_closures_and_dst_validation(
    admin: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, _ = admin
    room_id = str(create(client)["id"])
    body = {
        "kind": "schedule",
        "revision": 1,
        "hours_confirmed": True,
        "weekly": [
            {"weekday": 0, "start_minute": 540, "end_minute": 720},
            {"weekday": 0, "start_minute": 780, "end_minute": 1020},
        ],
        "exceptions": [
            {"date": "2026-12-25", "windows": []},
            {"date": "2026-12-26", "windows": [{"start_minute": 600, "end_minute": 840}]},
        ],
        "closures": [
            {
                "starts_at": "2026-12-27T10:00:00+11:00",
                "ends_at": "2026-12-27T11:00:00+11:00",
                "reason": "Maintenance",
            }
        ],
        "reason": "Seasonal hours",
    }
    response = client.put(
        f"/api/v1/admin/rooms/{room_id}/schedule", json=body, headers=headers(client, str(uuid4()))
    )
    assert response.status_code == 200, response.text
    read = client.get(f"/api/v1/admin/rooms/{room_id}/schedule").json()
    assert read["weekly"] == body["weekly"] and read["exceptions"] == body["exceptions"]
    assert read["closures"][0]["reason"] == "Maintenance"
    with Session(db_engine) as db:
        assert len(list(db.scalars(select(DateException)))) == 2
        assert len(list(db.scalars(select(ExceptionHours)))) == 1
        assert len(list(db.scalars(select(Closure)))) == 1
    body["revision"] = 2
    body["closures"] = [
        {
            "starts_at": "2027-04-04T02:15:00+11:00",
            "ends_at": "2027-04-04T03:00:00+10:00",
            "reason": "Ambiguous time",
        }
    ]
    assert (
        client.post(
            f"/api/v1/admin/rooms/{room_id}/impact", json=body, headers=headers(client)
        ).status_code
        == 422
    )
    body["closures"] = []
    body["weekly"] = [
        {"weekday": 0, "start_minute": 540, "end_minute": 720},
        {"weekday": 0, "start_minute": 600, "end_minute": 780},
    ]
    assert (
        client.post(
            f"/api/v1/admin/rooms/{room_id}/impact", json=body, headers=headers(client)
        ).status_code
        == 422
    )


def test_booking_created_after_preview_still_blocks_deactivation(
    admin: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, _ = admin
    item = create(client)
    room_id = UUID(str(item["id"]))
    with Session(db_engine) as db, db.begin():
        room = db.get(Room, room_id)
        assert room is not None
        room.active = True
        room.hours_confirmed = True
    body = {
        "kind": "room",
        "name": item["name"],
        "location": item["location"],
        "capacity": 4,
        "active": False,
        "revision": 1,
        "reason": "Close for inspection",
    }
    before = client.post(
        f"/api/v1/admin/rooms/{room_id}/impact", json=body, headers=headers(client)
    )
    assert before.json()["affected_count"] == 0
    now = datetime.now(UTC)
    with Session(db_engine) as db, db.begin():
        db.add(
            Booking(
                room_id=room_id,
                starts_at=now + timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
            )
        )
    response = client.put(
        f"/api/v1/admin/rooms/{room_id}", json=body, headers=headers(client, str(uuid4()))
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "BOOKINGS_AFFECTED"
    assert client.get(f"/api/v1/admin/rooms/{room_id}").json()["active"]
    after = client.post(f"/api/v1/admin/rooms/{room_id}/impact", json=body, headers=headers(client))
    assert after.json()["affected_count"] == 1


def test_admin_receipts_prevent_destructive_downgrade(
    admin: tuple[TestClient, AdminProvider], database_url: str, db_engine: Engine
) -> None:
    client, _ = admin
    item = create(client)
    with patch.dict(os.environ, {"ROOMBOOK_DATABASE_URL": database_url}):
        with pytest.raises(DBAPIError, match="Refusing to discard administrator retry history"):
            command.downgrade(Config("alembic.ini"), "0005")
    with Session(db_engine) as db:
        assert db.get(Room, UUID(str(item["id"]))) is not None
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0006"


def test_additive_upgrade_preserves_room_and_legacy_booking(
    database_url: str, db_engine: Engine, clean_database: None
) -> None:
    room_id, booking_id = uuid4(), uuid4()
    with patch.dict(os.environ, {"ROOMBOOK_DATABASE_URL": database_url}):
        config = Config("alembic.ini")
        command.downgrade(config, "0005")
        with db_engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO rooms(id,name,location,capacity,active,hours_confirmed) "
                    "VALUES (:id,'Legacy room','Campus',4,true,true)"
                ),
                {"id": room_id},
            )
            db.execute(
                text(
                    "INSERT INTO bookings(id,room_id,starts_at,ends_at) "
                    "VALUES (:id,:room,'2026-10-23T00:00Z','2026-10-23T01:00Z')"
                ),
                {"id": booking_id, "room": room_id},
            )
            before = db.execute(text("SELECT * FROM bookings")).one()
        command.upgrade(config, "head")
        with db_engine.connect() as db:
            assert db.execute(text("SELECT * FROM bookings")).one() == before
            assert db.execute(text("SELECT revision,active,hours_confirmed FROM rooms")).one() == (
                1,
                True,
                True,
            )
