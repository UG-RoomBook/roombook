from collections.abc import Iterator
from datetime import timedelta
from functools import partial
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.modules.bookings import router
from app.modules.bookings.models import Booking, BookingRequest
from app.modules.bookings.service import create_booking
from app.modules.identity.models import ApplicationUser
from tests.availability.test_service import END, NOW, START, add_room
from tests.identity.test_service import Harness, TrackingDatabase

pytestmark = pytest.mark.database
ORIGIN = "https://roombook.example"


@pytest.fixture
def booking_http(
    database_url: str, db_engine: Engine, clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Harness, dict[str, str], dict[str, str]]]:
    database = TrackingDatabase(database_url)
    harness = Harness(database, db_engine)
    harness.clock.now = NOW
    token = harness.establish()
    app = create_app(Settings(_env_file=None, database_url=database_url, auth_site_url=ORIGIN))
    app.state.identity_sessions = harness.service
    app.state.identity_cipher = harness.cipher
    monkeypatch.setattr(router, "create_booking", partial(create_booking, clock=lambda: NOW))
    with Session(db_engine) as session, session.begin():
        room_id = add_room(session).id
    headers = {
        "Cookie": f"__Host-roombook_session={token}",
        "Origin": ORIGIN,
        "X-CSRF-Token": harness.cipher.csrf_token(token),
        "Idempotency-Key": str(uuid4()),
    }
    body = {"room_id": str(room_id), "starts_at": START.isoformat(), "ends_at": END.isoformat()}
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            yield client, harness, headers, body
    finally:
        database.dispose()


def test_real_session_owned_creation_timeout_replay_and_logout(
    booking_http: tuple[TestClient, Harness, dict[str, str], dict[str, str]], db_engine: Engine
) -> None:
    client, harness, headers, body = booking_http
    response = client.post("/api/v1/bookings", headers=headers, json=body)
    assert response.status_code == 201
    assert response.json()["owner_id"] == str(
        harness.service.authenticate(headers["Cookie"].split("=", 1)[1]).user_id
    )
    assert set(response.json()) == {
        "id",
        "owner_id",
        "room_id",
        "starts_at",
        "ends_at",
        "status",
        "created_at",
    }
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    # Treat first response as lost; replay via a new client/service transaction.
    assert client.post("/api/v1/bookings", headers=headers, json=body).json() == response.json()
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    denied = client.post("/api/v1/bookings", headers=headers, json=body)
    assert denied.status_code == 401 and denied.headers["Cache-Control"] == "private, no-store"
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 1
        assert session.scalar(select(func.count()).select_from(BookingRequest)) == 1


@pytest.mark.parametrize(
    "case,status",
    [
        ("missing_cookie", 401),
        ("bad_cookie", 401),
        ("origin", 403),
        ("csrf", 403),
        ("cross_site", 403),
        ("recovery", 403),
        ("inactive", 403),
        ("expired", 401),
        ("missing_key", 422),
        ("bad_key", 422),
        ("owner", 422),
        ("status", 422),
        ("naive", 422),
        ("numeric", 422),
        ("overflow", 422),
        ("duration", 422),
        ("alignment", 422),
        ("horizon", 422),
        ("missing_room", 404),
    ],
)
def test_access_and_input_failures_are_private_and_create_nothing(
    booking_http: tuple[TestClient, Harness, dict[str, str], dict[str, str]],
    db_engine: Engine,
    case: str,
    status: int,
) -> None:
    client, harness, headers, body = booking_http
    data: dict[str, object] = dict(body)
    if case == "missing_cookie":
        headers.pop("Cookie")
    elif case == "bad_cookie":
        headers["Cookie"] = "__Host-roombook_session=wrong"
    elif case == "origin":
        headers.pop("Origin")
    elif case == "csrf":
        headers["X-CSRF-Token"] = "wrong"
    elif case == "cross_site":
        headers["Sec-Fetch-Site"] = "cross-site"
    elif case == "recovery":
        token = harness.establish(purpose="recovery")
        headers["Cookie"] = f"__Host-roombook_session={token}"
        headers["X-CSRF-Token"] = harness.cipher.csrf_token(token)
    elif case == "inactive":
        with Session(db_engine) as session, session.begin():
            user = session.scalars(select(ApplicationUser)).one()
            user.is_active = False
    elif case == "expired":
        harness.clock.advance(43201)
    elif case == "missing_key":
        headers.pop("Idempotency-Key")
    elif case == "bad_key":
        headers["Idempotency-Key"] = "not-a-uuid"
    elif case == "owner":
        data["owner_id"] = str(uuid4())
    elif case == "status":
        data["status"] = "cancelled"
    elif case == "naive":
        data["starts_at"] = "2026-10-19T02:00:00"
    elif case == "numeric":
        data["starts_at"] = 1792375200
    elif case == "overflow":
        data["starts_at"] = "0001-01-01T00:00:00+11:00"
    elif case == "duration":
        data["ends_at"] = (START + timedelta(minutes=15)).isoformat()
    elif case == "alignment":
        data["starts_at"] = (START + timedelta(minutes=1)).isoformat()
    elif case == "horizon":
        data["starts_at"] = (NOW + timedelta(days=15)).isoformat()
    elif case == "missing_room":
        data["room_id"] = str(uuid4())
    response = client.post("/api/v1/bookings", headers=headers, json=data)
    assert response.status_code == status, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "error" in response.json() and "request_id" in response.json()["error"]
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 0
        assert session.scalar(select(func.count()).select_from(BookingRequest)) == 0


def test_mismatch_and_conflict_contract(
    booking_http: tuple[TestClient, Harness, dict[str, str], dict[str, str]],
) -> None:
    client, _, headers, body = booking_http
    assert client.post("/api/v1/bookings", headers=headers, json=body).status_code == 201
    mismatch = client.post(
        "/api/v1/bookings", headers=headers, json={**body, "room_id": str(uuid4())}
    )
    assert (
        mismatch.status_code == 409 and mismatch.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"
    )
    conflict = client.post(
        "/api/v1/bookings", headers={**headers, "Idempotency-Key": str(uuid4())}, json=body
    )
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "ROOM_UNAVAILABLE"


def test_private_errors_and_unexpected_exception(
    booking_http: tuple[TestClient, Harness, dict[str, str], dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _, headers, body = booking_http

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret-database-parameter")

    monkeypatch.setattr(router, "create_booking", fail)
    response = client.post("/api/v1/bookings", headers=headers, json=body)
    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "secret-database-parameter" not in response.text + caplog.text
    assert client.put("/api/v1/bookings").headers["Cache-Control"] == "private, no-store"
    assert client.get("/api/v1/bookings/missing").headers["Cache-Control"] == "private, no-store"


def test_openapi_documents_session_csrf_idempotency_and_responses() -> None:
    app = create_app(Settings(_env_file=None, database_url=None))
    spec = app.openapi()
    operation = spec["paths"]["/api/v1/bookings"]["post"]
    assert operation["security"] == [{"SessionCookie": []}]
    assert set(operation["responses"]) == {"201", "401", "403", "404", "409", "422", "500", "503"}
    headers = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert headers["idempotency-key"]["required"] is True
    assert {"Origin", "X-CSRF-Token"} <= headers.keys()
    assert spec["components"]["schemas"]["BookingCreate"]["additionalProperties"] is False
