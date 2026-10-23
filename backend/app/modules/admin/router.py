from collections.abc import Iterator
from datetime import date, datetime, time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorResponse
from app.modules.admin import queries, service
from app.modules.admin.access import AdminRead, AdminWrite, recheck
from app.modules.admin.schemas import (
    Activity,
    AdminBooking,
    AdminRoom,
    AdminUser,
    BookingPage,
    Impact,
    Overview,
    Page,
    PageQuery,
    ReasonInput,
    RoomCreate,
    RoomUpdate,
    ScheduleRead,
    ScheduleUpdate,
    UserUpdate,
)
from app.modules.availability.policy import CAMPUS
from app.modules.identity.account_router import AccountsDependency, rate
from app.modules.identity.dependencies import ServiceDependency
from app.modules.identity.models import ApplicationUser

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Administration"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 429, 503)},
)
Key = Annotated[UUID, Header(alias="Idempotency-Key")]


def page_query(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> PageQuery:
    return PageQuery(limit=limit, offset=offset)


Paging = Annotated[PageQuery, Depends(page_query)]
Search = Annotated[str, Query(max_length=120)]


def read_transaction(actor: AdminRead, sessions: ServiceDependency) -> Iterator[Session]:
    with sessions.database.session() as db, db.begin():
        recheck(db, actor, sessions)
        yield db


ReadDB = Annotated[Session, Depends(read_transaction)]


def limit_write(request: Request, accounts: AccountsDependency, actor: AdminWrite) -> None:
    rate(request, accounts, "admin-write", str(actor.user_id))


WriteRate = Depends(limit_write)


@router.get("/overview", operation_id="adminOverview")
def overview(db: ReadDB, sessions: ServiceDependency) -> Overview:
    return queries.overview(db, sessions._now())


@router.get("/rooms", operation_id="adminRooms")
def rooms(db: ReadDB, page: Paging, search: Search = "") -> Page[AdminRoom]:
    return queries.rooms(db, page, search)


@router.get("/rooms/{room_id}", operation_id="adminRoom")
def room(room_id: UUID, db: ReadDB) -> AdminRoom:
    return AdminRoom.model_validate(queries.room(db, room_id))


@router.post("/rooms", operation_id="adminCreateRoom", dependencies=[WriteRate], status_code=201)
def create_room(
    body: RoomCreate, actor: AdminWrite, sessions: ServiceDependency, key: Key
) -> AdminRoom:
    return service.mutate(
        sessions,
        actor,
        key,
        "room.create",
        None,
        body,
        AdminRoom,
        lambda db, now: service.create_room(db, actor.user_id, body, now),
    )


@router.put("/rooms/{room_id}", operation_id="adminUpdateRoom", dependencies=[WriteRate])
def update_room(
    room_id: UUID, body: RoomUpdate, actor: AdminWrite, sessions: ServiceDependency, key: Key
) -> AdminRoom:
    return service.mutate(
        sessions,
        actor,
        key,
        "room.update",
        room_id,
        body,
        AdminRoom,
        lambda db, now: service.update_room(db, actor.user_id, room_id, body, now),
    )


@router.get("/rooms/{room_id}/schedule", operation_id="adminSchedule")
def schedule(room_id: UUID, db: ReadDB) -> ScheduleRead:
    return queries.schedule(db, queries.room(db, room_id))


@router.put(
    "/rooms/{room_id}/schedule", operation_id="adminUpdateSchedule", dependencies=[WriteRate]
)
def update_schedule(
    room_id: UUID, body: ScheduleUpdate, actor: AdminWrite, sessions: ServiceDependency, key: Key
) -> ScheduleRead:
    return service.mutate(
        sessions,
        actor,
        key,
        "schedule.update",
        room_id,
        body,
        ScheduleRead,
        lambda db, now: service.update_schedule(db, actor.user_id, room_id, body, now),
    )


@router.post("/rooms/{room_id}/impact", operation_id="adminRoomImpact", dependencies=[WriteRate])
def impact(
    room_id: UUID, body: RoomUpdate | ScheduleUpdate, db: ReadDB, sessions: ServiceDependency
) -> Impact:
    return service.impact(db, room_id, body, sessions._now())


@router.get("/bookings", operation_id="adminBookings")
def bookings(
    db: ReadDB,
    sessions: ServiceDependency,
    page: Paging,
    status: Literal["all", "upcoming", "ongoing", "completed", "cancelled"] = "all",
    room_id: UUID | None = None,
    search: Search = "",
    day: date | None = None,
) -> BookingPage:
    return queries.bookings(
        db,
        page,
        sessions._now(),
        status,
        room_id,
        search,
        datetime.combine(day, time.min, CAMPUS) if day else None,
    )


@router.get("/bookings/{booking_id}", operation_id="adminBooking")
def booking(booking_id: UUID, db: ReadDB, sessions: ServiceDependency) -> AdminBooking:
    return queries.booking(db, booking_id, sessions._now())


@router.post(
    "/bookings/{booking_id}/cancel", operation_id="adminCancelBooking", dependencies=[WriteRate]
)
def cancel(
    booking_id: UUID, body: ReasonInput, actor: AdminWrite, sessions: ServiceDependency, key: Key
) -> AdminBooking:
    return service.mutate(
        sessions,
        actor,
        key,
        "booking.cancel",
        booking_id,
        body,
        AdminBooking,
        lambda db, now: service.cancel_booking(db, actor.user_id, booking_id, body, now),
    )


@router.get("/users", operation_id="adminUsers")
def users(db: ReadDB, page: Paging, search: Search = "") -> Page[AdminUser]:
    return queries.users(db, page, search)


@router.get("/users/{user_id}", operation_id="adminUser")
def user(user_id: UUID, db: ReadDB) -> AdminUser:
    item = db.get(ApplicationUser, user_id)
    if item is None:
        raise ApiError(404, "USER_NOT_FOUND", "The user was not found.")
    return AdminUser.model_validate(item)


@router.put("/users/{user_id}", operation_id="adminUpdateUser", dependencies=[WriteRate])
def update_user(
    user_id: UUID, body: UserUpdate, actor: AdminWrite, sessions: ServiceDependency, key: Key
) -> AdminUser:
    return service.mutate(
        sessions,
        actor,
        key,
        "user.update",
        user_id,
        body,
        AdminUser,
        lambda db, now: service.update_user(db, actor.user_id, user_id, body, now),
        access=True,
    )


@router.get("/activity", operation_id="adminActivity")
def activity(
    db: ReadDB,
    page: Paging,
    action: Search = "",
    target: UUID | None = None,
    actor: UUID | None = None,
) -> Page[Activity]:
    return queries.activity(db, page, action, target, actor)
