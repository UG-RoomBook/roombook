from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.admin.models import AdminRequest
from app.modules.admin.schemas import AdminUser, UserUpdate
from app.modules.admin.service import mutate, update_user
from app.modules.bookings.models import Booking
from app.modules.identity.models import ApplicationUser, AuditEvent, AuthSession
from app.modules.rooms.models import Room
from tests.admin.conftest import complete_mfa, headers
from tests.admin_provider import AdminProvider
from tests.identity.test_accounts import login

pytestmark = pytest.mark.database


def create(client: TestClient, name: str = "Quiet room") -> dict[str, object]:
    response = client.post(
        "/api/v1/admin/rooms",
        headers=headers(client, str(uuid4())),
        json={"name": name, "location": "Level 2", "capacity": 4, "reason": "New study space"},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_admin_requires_role_verified_mfa_and_standard_live_session(
    mfa_account: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, _ = mfa_account
    assert client.get("/api/v1/admin/overview").status_code == 401
    user_id = UUID(login(client).json()["user"]["id"])
    assert client.get("/api/v1/admin/overview").json()["error"]["code"] == "ADMIN_REQUIRED"
    with Session(db_engine) as db, db.begin():
        db.execute(update(ApplicationUser).values(role="Admin"))
    assert client.get("/api/v1/admin/overview").json()["error"]["code"] == "MFA_REQUIRED"
    complete_mfa(client)
    response = client.get("/api/v1/admin/overview")
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    assert response.json()["active_users"] == 1
    with Session(db_engine) as db, db.begin():
        db.execute(
            update(ApplicationUser).where(ApplicationUser.id == user_id).values(is_active=False)
        )
    assert client.get("/api/v1/admin/users").status_code == 403


def test_room_creation_replay_csrf_paging_and_stale_revision(
    admin: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, _ = admin
    key = str(uuid4())
    body = {"name": "Quiet room", "location": "Level 2", "capacity": 4, "reason": "Create"}
    assert client.post("/api/v1/admin/rooms", json=body).status_code in (403, 422)
    first = client.post("/api/v1/admin/rooms", headers=headers(client, key), json=body)
    assert first.status_code == 201, first.text
    assert not first.json()["active"] and not first.json()["hours_confirmed"]
    assert (
        client.post("/api/v1/admin/rooms", headers=headers(client, key), json=body).json()
        == first.json()
    )
    assert (
        client.post(
            "/api/v1/admin/rooms", headers=headers(client, key), json={**body, "capacity": 8}
        ).status_code
        == 409
    )
    room_id = first.json()["id"]
    assert client.get(f"/api/v1/admin/rooms/{room_id}").json() == first.json()
    assert client.get("/api/v1/admin/rooms?limit=1&search=quiet").json()["total"] == 1
    assert client.get("/api/v1/admin/rooms?limit=101").status_code == 422
    update_body = {**body, "active": True, "revision": 1}
    assert (
        client.put(
            f"/api/v1/admin/rooms/{room_id}",
            headers=headers(client, str(uuid4())),
            json=update_body,
        ).json()["error"]["code"]
        == "HOURS_UNCONFIRMED"
    )
    update_body.update(active=False, name="Quiet study")
    response = client.put(
        f"/api/v1/admin/rooms/{room_id}", headers=headers(client, str(uuid4())), json=update_body
    )
    assert response.status_code == 200 and response.json()["revision"] == 2
    assert (
        client.put(
            f"/api/v1/admin/rooms/{room_id}",
            headers=headers(client, str(uuid4())),
            json=update_body,
        ).json()["error"]["code"]
        == "REVISION_CONFLICT"
    )
    with Session(db_engine) as db:
        assert db.scalar(select(func.count()).select_from(Room)) == 1
        assert db.scalar(select(func.count()).select_from(AdminRequest)) == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "admin.room.created")
            )
            == 1
        )


def test_schedule_impact_blocks_edits_and_cancellation_restores_availability(
    admin: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, _ = admin
    room_id = str(create(client)["id"])
    schedule = {
        "kind": "schedule",
        "revision": 1,
        "hours_confirmed": True,
        "weekly": [{"weekday": day, "start_minute": 0, "end_minute": 1440} for day in range(7)],
        "exceptions": [],
        "closures": [],
        "reason": "Confirmed hours",
    }
    response = client.put(
        f"/api/v1/admin/rooms/{room_id}/schedule",
        json=schedule,
        headers=headers(client, str(uuid4())),
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 2
    room = client.get(f"/api/v1/admin/rooms/{room_id}").json()
    activate = {k: v for k, v in room.items() if k not in ("id", "hours_confirmed")}
    activate.update(active=True, reason="Open room")
    assert (
        client.put(
            f"/api/v1/admin/rooms/{room_id}", json=activate, headers=headers(client, str(uuid4()))
        ).status_code
        == 200
    )
    now = datetime.now(UTC)
    booking_id = uuid4()
    with Session(db_engine) as db, db.begin():
        db.add(
            Booking(
                id=booking_id,
                room_id=UUID(room_id),
                starts_at=now + timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
            )
        )
    schedule.update(revision=3, weekly=[])
    impact = client.post(
        f"/api/v1/admin/rooms/{room_id}/impact", json=schedule, headers=headers(client)
    )
    assert impact.status_code == 200 and impact.json()["affected_count"] == 1
    assert impact.json()["affected_bookings"][0]["owner_label"] == "Legacy booking"
    blocked = client.put(
        f"/api/v1/admin/rooms/{room_id}/schedule",
        json=schedule,
        headers=headers(client, str(uuid4())),
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "BOOKINGS_AFFECTED"
    assert client.get(f"/api/v1/admin/rooms/{room_id}/schedule").json()["revision"] == 3
    key = str(uuid4())
    cancelled = client.post(
        f"/api/v1/admin/bookings/{booking_id}/cancel",
        json={"reason": "Room maintenance"},
        headers=headers(client, key),
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "Cancelled"
    assert (
        client.post(
            f"/api/v1/admin/bookings/{booking_id}/cancel",
            json={"reason": "Room maintenance"},
            headers=headers(client, key),
        ).json()
        == cancelled.json()
    )
    assert (
        client.put(
            f"/api/v1/admin/rooms/{room_id}/schedule",
            json=schedule,
            headers=headers(client, str(uuid4())),
        ).status_code
        == 200
    )
    assert client.get("/api/v1/admin/bookings?status=cancelled").json()["total"] == 1
    assert (
        client.get(f"/api/v1/admin/activity?target={booking_id}&action=cancelled").json()["total"]
        == 1
    )


@pytest.mark.parametrize("status", ["upcoming", "ongoing", "completed", "cancelled"])
def test_booking_filter_and_cancellation_policy(
    admin: tuple[TestClient, AdminProvider], db_engine: Engine, status: str
) -> None:
    client, _ = admin
    room_id = UUID(str(create(client)["id"]))
    now = datetime.now(UTC)
    booking_id = uuid4()
    with Session(db_engine) as db, db.begin():
        room = db.get(Room, room_id)
        assert room is not None
        room.active = True
        room.hours_confirmed = True
        from app.modules.availability.models import WeeklyHours

        for day in range(7):
            db.add(WeeklyHours(room_id=room_id, weekday=day, start_minute=0, end_minute=1440))
        db.add(
            Booking(
                id=booking_id,
                room_id=room_id,
                starts_at=now + timedelta(hours=1)
                if status == "upcoming"
                else now - timedelta(hours=1),
                ends_at=now - timedelta(minutes=1)
                if status == "completed"
                else now + timedelta(hours=2),
                status="cancelled" if status == "cancelled" else "active",
                cancelled_at=now if status == "cancelled" else None,
            )
        )
    listing = client.get(f"/api/v1/admin/bookings?status={status}").json()
    assert listing["total"] == 1
    assert datetime.fromisoformat(listing["generated_at"]) >= now
    # Date and status are independent filters, including cancelled reservations.
    from app.modules.availability.policy import CAMPUS

    booking_day = datetime.fromisoformat(listing["items"][0]["starts_at"]).astimezone(CAMPUS).date()
    dated = client.get(f"/api/v1/admin/bookings?status={status}&day={booking_day}").json()
    assert dated["total"] == 1
    if status == "cancelled":
        assert client.get("/api/v1/admin/overview").json()["bookings_today"] == 0
    assert client.get(f"/api/v1/admin/bookings/{booking_id}").json()["status"].lower() == status
    response = client.post(
        f"/api/v1/admin/bookings/{booking_id}/cancel",
        json={"reason": "Operational change"},
        headers=headers(client, str(uuid4())),
    )
    assert response.status_code == (409 if status == "completed" else 200), response.text


def test_user_changes_revoke_sessions_preserve_bookings_and_require_recent_mfa(
    admin: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, _ = admin
    from tests.identity.test_accounts import ORIGIN, PASSWORD

    member_client = TestClient(client.app, base_url=ORIGIN)
    member_login = member_client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "student@example.com", "password": PASSWORD},
    )
    user_id = UUID(member_login.json()["user"]["id"])
    room_id = UUID(str(create(client)["id"]))
    booking_id = uuid4()
    with Session(db_engine) as db, db.begin():
        now = datetime.now(UTC)
        db.add(
            Booking(
                id=booking_id,
                room_id=room_id,
                owner_id=user_id,
                starts_at=now + timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
            )
        )
    body = {"revision": 1, "role": "Admin", "is_active": True, "reason": "New team administrator"}
    with Session(db_engine) as db, db.begin():
        db.execute(
            update(AuthSession).values(mfa_verified_at=datetime.now(UTC) - timedelta(minutes=11))
        )
    response = client.put(
        f"/api/v1/admin/users/{user_id}", json=body, headers=headers(client, str(uuid4()))
    )
    assert response.json()["error"]["code"] == "MFA_RECENT_REQUIRED"
    with Session(db_engine) as db, db.begin():
        db.execute(update(AuthSession).values(mfa_verified_at=datetime.now(UTC)))
    response = client.put(
        f"/api/v1/admin/users/{user_id}", json=body, headers=headers(client, str(uuid4()))
    )
    assert response.status_code == 200 and response.json()["role"] == "Admin"
    assert member_client.get("/api/v1/auth/session").status_code == 401
    with Session(db_engine) as db:
        booking = db.get(Booking, booking_id)
        assert booking is not None and booking.status == "active" and booking.owner_id == user_id
    assert client.get("/api/v1/admin/users?search=student").json()["total"] == 1
    assert client.get(f"/api/v1/admin/users/{user_id}").json()["revision"] == 2
    body.update(revision=2, is_active=False)
    assert (
        client.put(
            f"/api/v1/admin/users/{user_id}", json=body, headers=headers(client, str(uuid4()))
        ).status_code
        == 200
    )
    actor_id = client.get("/api/v1/auth/session").json()["user"]["id"]
    body.update(revision=1, role="Member")
    assert (
        client.put(
            f"/api/v1/admin/users/{actor_id}", json=body, headers=headers(client, str(uuid4()))
        ).json()["error"]["code"]
        == "LAST_ADMIN"
    )


def test_concurrent_last_admin_guard(
    admin: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, _ = admin
    service = client.app.state.identity_sessions  # type: ignore[attr-defined]
    token = client.cookies.get("__Host-roombook_session")
    actor = service.authenticate(token)
    other_id = uuid4()
    with Session(db_engine) as db, db.begin():
        db.add(ApplicationUser(id=other_id, role="Admin"))
    body = UserUpdate(revision=1, role="Member", is_active=True, reason="Team handover")

    def demote(target: UUID) -> str:
        try:
            mutate(
                service,
                actor,
                uuid4(),
                "user.update",
                target,
                body,
                AdminUser,
                lambda db, now: update_user(db, actor.user_id, target, body, now),
                access=True,
            )
            return "ok"
        except ApiError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(demote, [actor.user_id, other_id]))
    assert results.count("ok") == 1
    with Session(db_engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ApplicationUser)
                .where(ApplicationUser.role == "Admin", ApplicationUser.is_active)
            )
            == 1
        )


def test_transaction_rechecks_demoted_actor(
    admin: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, _ = admin
    service = client.app.state.identity_sessions  # type: ignore[attr-defined]
    actor = service.authenticate(client.cookies.get("__Host-roombook_session"))
    with Session(db_engine) as db, db.begin():
        db.execute(update(ApplicationUser).values(role="Member"))
    body = UserUpdate(revision=1, role="Admin", is_active=True, reason="Rejected")
    with pytest.raises(ApiError) as error:
        mutate(
            service,
            replace(actor, role="Admin"),
            uuid4(),
            "user.update",
            actor.user_id,
            body,
            AdminUser,
            lambda db, now: update_user(db, actor.user_id, actor.user_id, body, now),
            access=True,
        )
    assert error.value.code == "ADMIN_REQUIRED"
