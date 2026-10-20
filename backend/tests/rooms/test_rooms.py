from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.dependencies import get_session
from app.main import create_app
from app.modules.availability.models import WeeklyHours
from app.modules.availability.policy import current_time
from app.modules.bookings.models import Booking
from app.modules.rooms.models import Room

pytestmark = pytest.mark.database


@pytest.fixture
def room_client(db_session: Session, database_url: str) -> Iterator[TestClient]:
    application = create_app(Settings(database_url=database_url))

    def session_override() -> Iterator[Session]:
        yield db_session

    application.dependency_overrides[get_session] = session_override
    application.dependency_overrides[current_time] = lambda: datetime(2026, 10, 18, tzinfo=UTC)
    with TestClient(application) as client:
        yield client


def add_room(session: Session, name: str, *, active: bool = True) -> Room:
    room = Room(
        id=uuid4(), name=name, location="West Wing", capacity=4, active=active, hours_confirmed=True
    )
    session.add(room)
    session.flush()
    session.add_all(
        [
            WeeklyHours(room_id=room.id, weekday=day, start_minute=0, end_minute=1440)
            for day in range(7)
        ]
    )
    session.flush()
    return room


def add_booking(
    session: Session,
    room: Room,
    *,
    start: str = "2026-10-19T13:00:00+11:00",
    end: str = "2026-10-19T14:00:00+11:00",
    cancelled: bool = False,
) -> Booking:
    booking = Booking(
        id=uuid4(),
        room_id=room.id,
        starts_at=datetime.fromisoformat(start),
        ends_at=datetime.fromisoformat(end),
        status="cancelled" if cancelled else "active",
        created_at=datetime(2026, 10, 18, tzinfo=UTC),
        cancelled_at=datetime(2026, 10, 18, 1, tzinfo=UTC) if cancelled else None,
    )
    session.add(booking)
    session.flush()
    return booking


def test_metadata_includes_inactive_rooms_without_availability(
    room_client: TestClient, db_session: Session
) -> None:
    add_room(db_session, "Studio")
    add_room(db_session, "Forum", active=False)

    response = room_client.get("/api/v1/rooms")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [room["name"] for room in body["items"]] == ["Forum", "Studio"]
    assert body["items"][0]["active"] is False
    assert all("available" not in room for room in body["items"])
    assert all(room["capacity"] == 4 and room["location"] == "West Wing" for room in body["items"])
    assert all(UUID(room["id"]) for room in body["items"])


@pytest.mark.parametrize("offset", [50, 9_223_372_036_854_775_807])
def test_empty_room_list_has_a_complete_pagination_envelope(
    room_client: TestClient, offset: int
) -> None:
    response = room_client.get("/api/v1/rooms", params={"limit": 100, "offset": offset})

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 100, "offset": offset}


@pytest.mark.parametrize(
    ("start", "end", "available"),
    [
        ("2026-10-19T12:00:00+11:00", "2026-10-19T13:00:00+11:00", True),
        ("2026-10-19T14:00:00+11:00", "2026-10-19T15:00:00+11:00", True),
        ("2026-10-19T13:00:00+11:00", "2026-10-19T14:00:00+11:00", False),
        ("2026-10-19T12:30:00+11:00", "2026-10-19T13:30:00+11:00", False),
        ("2026-10-19T13:30:00+11:00", "2026-10-19T14:30:00+11:00", False),
        ("2026-10-19T12:30:00+11:00", "2026-10-19T14:30:00+11:00", False),
        ("2026-10-19T13:15:00+11:00", "2026-10-19T13:45:00+11:00", False),
        ("2026-10-19T02:00:00Z", "2026-10-19T03:00:00Z", False),
    ],
)
def test_half_open_interval_availability(
    room_client: TestClient, db_session: Session, start: str, end: str, available: bool
) -> None:
    studio = add_room(db_session, "Studio")
    add_booking(db_session, studio)

    response = room_client.get("/api/v1/rooms", params={"starts_at": start, "ends_at": end})

    assert response.status_code == 200
    assert response.json()["items"][0]["available"] is available


def test_cancelled_bookings_do_not_block_and_inactive_rooms_stay_unavailable(
    room_client: TestClient, db_session: Session
) -> None:
    studio = add_room(db_session, "Studio")
    add_booking(db_session, studio, cancelled=True)
    add_room(db_session, "Forum", active=False)

    response = room_client.get(
        "/api/v1/rooms",
        params={
            "starts_at": "2026-10-19T13:00:00+11:00",
            "ends_at": "2026-10-19T14:00:00+11:00",
        },
    )

    assert response.status_code == 200
    assert {room["name"]: room["available"] for room in response.json()["items"]} == {
        "Forum": False,
        "Studio": True,
    }


def test_available_room_is_not_blocked_by_another_rooms_booking(
    room_client: TestClient, db_session: Session
) -> None:
    add_room(db_session, "Forum")
    studio = add_room(db_session, "Studio")
    add_booking(db_session, studio)

    response = room_client.get(
        "/api/v1/rooms",
        params={
            "starts_at": "2026-10-19T13:00:00+11:00",
            "ends_at": "2026-10-19T14:00:00+11:00",
        },
    )

    assert response.status_code == 200
    assert {room["name"]: room["available"] for room in response.json()["items"]} == {
        "Forum": True,
        "Studio": False,
    }


def test_offset_equivalent_requests_match_across_dst(
    room_client: TestClient, db_session: Session
) -> None:
    assert isinstance(room_client.app, FastAPI)
    room_client.app.dependency_overrides[current_time] = lambda: datetime(2026, 4, 4, tzinfo=UTC)
    studio = add_room(db_session, "Studio")
    add_booking(
        db_session,
        studio,
        start="2026-04-05T02:30:00+11:00",
        end="2026-04-05T02:00:00+10:00",
    )

    local_response = room_client.get(
        "/api/v1/rooms",
        params={
            "starts_at": "2026-04-05T02:30:00+11:00",
            "ends_at": "2026-04-05T02:00:00+10:00",
        },
    )
    utc_response = room_client.get(
        "/api/v1/rooms",
        params={"starts_at": "2026-04-04T15:30:00Z", "ends_at": "2026-04-04T16:00:00Z"},
    )

    assert local_response.status_code == utc_response.status_code == 422
    assert local_response.json()["error"]["code"] == utc_response.json()["error"]["code"]


def test_pagination_is_stable_and_total_includes_unavailable_rooms(
    room_client: TestClient, db_session: Session
) -> None:
    for name in ["Studio", "Atrium", "Forum"]:
        room = add_room(db_session, name)
        if name == "Atrium":
            add_booking(db_session, room)
    parameters = {
        "starts_at": "2026-10-19T13:00:00+11:00",
        "ends_at": "2026-10-19T14:00:00+11:00",
        "limit": 1,
    }

    first = room_client.get("/api/v1/rooms", params={**parameters, "offset": 0})
    second = room_client.get("/api/v1/rooms", params={**parameters, "offset": 1})
    repeated = room_client.get("/api/v1/rooms", params={**parameters, "offset": 1})
    beyond = room_client.get("/api/v1/rooms", params={**parameters, "offset": 3})

    assert all(response.status_code == 200 for response in [first, second, repeated, beyond])
    assert first.json()["items"][0]["name"] == "Atrium"
    assert first.json()["items"][0]["available"] is False
    assert second.json()["items"][0]["name"] == "Forum"
    assert second.json() == repeated.json()
    assert beyond.json() == {"items": [], "total": 3, "limit": 1, "offset": 3}
    assert all(response.json()["total"] == 3 for response in [first, second, repeated])


@pytest.mark.parametrize("count", [1, 25, 100])
def test_availability_uses_six_queries_for_a_page(
    room_client: TestClient, db_session: Session, db_engine: Engine, count: int
) -> None:
    for index in range(count):
        add_room(db_session, f"Room {index:02}")
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_engine, "before_cursor_execute", record_statement)
    try:
        response = room_client.get(
            "/api/v1/rooms",
            params={
                "starts_at": "2026-10-19T13:00:00+11:00",
                "ends_at": "2026-10-19T14:00:00+11:00",
                "limit": count,
            },
        )
    finally:
        event.remove(db_engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert len(response.json()["items"]) == count
    assert len(statements) == 6


def test_unconfirmed_room_is_unavailable_but_metadata_is_preserved(
    room_client: TestClient, db_session: Session
) -> None:
    room = add_room(db_session, "Unconfirmed")
    room.hours_confirmed = False
    db_session.flush()
    response = room_client.get(
        "/api/v1/rooms",
        params={"starts_at": "2026-10-19T02:00Z", "ends_at": "2026-10-19T03:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["available"] is False
    assert "available" not in room_client.get("/api/v1/rooms").json()["items"][0]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-10-18T00:00Z", "2026-10-18T01:00Z"),  # Now, not future.
        ("2026-11-01T00:15Z", "2026-11-01T01:15Z"),  # Beyond fourteen elapsed days.
        ("2026-10-19T02:01Z", "2026-10-19T03:01Z"),
        ("2026-10-19T02:00Z", "2026-10-19T02:15Z"),
        ("2026-10-19T02:00Z", "2026-10-19T05:00Z"),
    ],
)
def test_api_enforces_shared_booking_policy(room_client: TestClient, start: str, end: str) -> None:
    response = room_client.get("/api/v1/rooms", params={"starts_at": start, "ends_at": end})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"][0]["code"] == "booking_policy"


@pytest.mark.parametrize(
    "parameters",
    [
        {"starts_at": "2026-10-19T13:00:00+11:00"},
        {"ends_at": "2026-10-19T14:00:00+11:00"},
        {"starts_at": "2026-10-19T13:00:00", "ends_at": "2026-10-19T14:00:00+11:00"},
        {"starts_at": "invalid", "ends_at": "2026-10-19T14:00:00+11:00"},
        {"starts_at": "1792375200", "ends_at": "1792378800"},
        {"starts_at": "2026-10-19T14:00:00Z", "ends_at": "2026-10-19T14:00:00Z"},
        {"starts_at": "2026-10-19T15:00:00Z", "ends_at": "2026-10-19T14:00:00Z"},
        {"limit": "0"},
        {"limit": "101"},
        {"offset": "-1"},
        {"offset": "9223372036854775808"},
        {
            "starts_at": "0001-01-01T00:00:00+14:00",
            "ends_at": "0001-01-01T01:00:00+14:00",
        },
        {
            "starts_at": "9999-12-31T22:00:00-14:00",
            "ends_at": "9999-12-31T23:00:00-14:00",
        },
    ],
)
def test_invalid_query_returns_consistent_validation_error(
    room_client: TestClient, parameters: dict[str, str]
) -> None:
    response = room_client.get("/api/v1/rooms", params=parameters)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["request_id"] == response.headers["x-request-id"]
    assert error["details"]


def test_database_connection_failure_is_sanitized() -> None:
    application = create_app(
        Settings(database_url="postgresql+psycopg://private:secret@127.0.0.1:1/roombook_test")
    )

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/rooms")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert "secret" not in response.text
    assert "SELECT" not in response.text
