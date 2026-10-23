"""Atomic admin writes, durable replay receipts and booking-preserving calendar changes."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.admin import queries
from app.modules.admin.access import recheck
from app.modules.admin.models import AdminRequest
from app.modules.admin.schemas import (
    AdminBooking,
    AdminRoom,
    AdminUser,
    Impact,
    ReasonInput,
    RoomCreate,
    RoomUpdate,
    ScheduleRead,
    ScheduleUpdate,
    UserUpdate,
)
from app.modules.availability.models import Closure, DateException, ExceptionHours, WeeklyHours
from app.modules.availability.policy import Calendar, Hours, Interval
from app.modules.availability.service import load_calendars, room_in_transaction
from app.modules.bookings.models import Booking
from app.modules.identity.models import ApplicationUser, AuditEvent, AuthSession
from app.modules.identity.service import SessionResult, SessionService
from app.modules.rooms.models import Room

T = TypeVar("T", bound=BaseModel)
ACCESS_LOCK = 450235178471  # Shared by bootstrap and all role/status changes.


def revision(actual: int, expected: int) -> None:
    if actual != expected:
        raise ApiError(409, "REVISION_CONFLICT", "This record changed. Reload it before saving.")


def audit(
    db: Session,
    actor: UUID,
    target: UUID,
    action: str,
    body: BaseModel,
    now: datetime,
    before: BaseModel | None = None,
    after: BaseModel | None = None,
) -> None:
    details = {"reason": getattr(body, "reason", "")}
    if before:
        details["before"] = before.model_dump(mode="json")
    if after:
        details["after"] = after.model_dump(mode="json")
    db.add(
        AuditEvent(
            actor_user_id=actor, target_id=target, action=action, occurred_at=now, details=details
        )
    )


def mutate[T: BaseModel](
    service: SessionService,
    actor: SessionResult,
    key: UUID,
    action: str,
    target: UUID | None,
    body: BaseModel,
    model: type[T],
    apply: Callable[[Session, datetime], T],
    *,
    access: bool = False,
) -> T:
    digest = hashlib.sha256(
        json.dumps(
            {"action": action, "target": str(target), "body": body.model_dump(mode="json")},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    lock = int.from_bytes(
        hashlib.sha256(f"admin/{actor.user_id}/{key}".encode()).digest()[:8], "big", signed=True
    )
    try:
        with service.database.session() as db, db.begin():
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
            if access:
                db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ACCESS_LOCK})
                # Stable order avoids reciprocal user/actor deadlocks.
                list(
                    db.scalars(
                        select(ApplicationUser)
                        .where(ApplicationUser.id.in_({actor.user_id, target} - {None}))
                        .order_by(ApplicationUser.id)
                        .with_for_update()
                    )
                )
            now = recheck(db, actor, service, recent=access, exclusive=access)
            receipt = db.get(AdminRequest, (actor.user_id, key))
            if receipt:
                if receipt.payload_hash != digest:
                    raise ApiError(
                        409, "IDEMPOTENCY_CONFLICT", "Use the original request to retry."
                    )
                return model.model_validate(receipt.result)
            result = apply(db, now)
            db.add(
                AdminRequest(
                    user_id=actor.user_id,
                    key=key,
                    payload_hash=digest,
                    result=result.model_dump(mode="json"),
                    created_at=now,
                )
            )
            return result
    except IntegrityError:
        raise ApiError(
            409, "ADMIN_CONFLICT", "A conflicting record exists. Reload and try again."
        ) from None
    except OperationalError:
        raise ApiError(
            409, "ADMIN_BUSY", "Another update is in progress. Retry this request."
        ) from None


def create_room(db: Session, actor: UUID, body: RoomCreate, now: datetime) -> AdminRoom:
    item = Room(
        name=body.name,
        location=body.location,
        capacity=body.capacity,
        active=False,
        hours_confirmed=False,
        revision=1,
    )
    db.add(item)
    db.flush()
    result = AdminRoom.model_validate(item)
    audit(db, actor, item.id, "admin.room.created", body, now, after=result)
    return result


def update_room(
    db: Session, actor: UUID, room_id: UUID, body: RoomUpdate, now: datetime
) -> AdminRoom:
    with room_in_transaction(db, room_id) as guard:
        item = guard.room
        revision(item.revision, body.revision)
        if body.active and not item.hours_confirmed:
            raise ApiError(
                409, "HOURS_UNCONFIRMED", "Confirm the room's schedule before activating it."
            )
        before = AdminRoom.model_validate(item)
        item.name, item.location, item.capacity, item.active = (
            body.name,
            body.location,
            body.capacity,
            body.active,
        )
        item.revision += 1
        result = AdminRoom.model_validate(item)
        audit(db, actor, item.id, "admin.room.updated", body, now, before, result)
        return result


def update_schedule(
    db: Session, actor: UUID, room_id: UUID, body: ScheduleUpdate, now: datetime
) -> ScheduleRead:
    with room_in_transaction(db, room_id) as guard:
        item = guard.room
        revision(item.revision, body.revision)
        if item.active and not body.hours_confirmed:
            raise ApiError(
                409, "HOURS_UNCONFIRMED", "Deactivate the room before unconfirming hours."
            )
        before = queries.schedule(db, item)
        db.execute(delete(WeeklyHours).where(WeeklyHours.room_id == room_id))
        db.execute(delete(DateException).where(DateException.room_id == room_id))
        db.execute(delete(Closure).where(Closure.room_id == room_id))
        for window in body.weekly:
            db.add(WeeklyHours(room_id=room_id, **window.model_dump()))
        for exception in body.exceptions:
            record = DateException(room_id=room_id, date=exception.date)
            db.add(record)
            db.flush()
            for exception_window in exception.windows:
                db.add(ExceptionHours(exception_id=record.id, **exception_window.model_dump()))
        for closure in body.closures:
            db.add(Closure(room_id=room_id, **closure.model_dump()))
        item.hours_confirmed = body.hours_confirmed
        item.revision += 1
        db.flush()
        result = queries.schedule(db, item)
        audit(db, actor, item.id, "admin.schedule.updated", body, now, before, result)
        return result


def impact(db: Session, room_id: UUID, body: RoomUpdate | ScheduleUpdate, now: datetime) -> Impact:
    item = queries.room(db, room_id)
    revision(item.revision, body.revision)
    rows = db.execute(
        queries.booking_query()
        .where(Booking.room_id == room_id, Booking.status == "active", Booking.ends_at > now)
        .order_by(Booking.starts_at, Booking.id)
    ).all()
    affected: list[AdminBooking] = []
    if rows:
        if isinstance(body, ScheduleUpdate):
            calendar = Calendar(item.active, body.hours_confirmed, {}, {}, [], [])
            for window in body.weekly:
                calendar.weekly.setdefault(window.weekday, []).append(
                    Hours(window.start_minute, window.end_minute)
                )
            calendar.exceptions = {
                e.date: [Hours(w.start_minute, w.end_minute) for w in e.windows]
                for e in body.exceptions
            }
            calendar.closures = [Interval(c.starts_at, c.ends_at) for c in body.closures]
        else:
            calendar = load_calendars(
                db,
                [item],
                starts_at=min(r[0].starts_at for r in rows),
                ends_at=max(r[0].ends_at for r in rows),
            )[item.id]
            calendar.active = body.active
        affected = [
            queries.booking_view(row[0], row[1], row[2], now)
            for row in rows
            if not calendar.supports(Interval(row[0].starts_at, row[0].ends_at))
        ]
    return Impact(
        revision=item.revision,
        affected_count=len(affected),
        affected_bookings=affected[:100],
        generated_at=now,
    )


def cancel_booking(
    db: Session, actor: UUID, booking_id: UUID, body: ReasonInput, now: datetime
) -> AdminBooking:
    row = db.get(Booking, booking_id)
    if row is None:
        raise ApiError(404, "BOOKING_NOT_FOUND", "The booking was not found.")
    with room_in_transaction(db, row.room_id):
        db.refresh(row, with_for_update=True)
        if row.status == "cancelled":
            return queries.booking(db, booking_id, now)
        if row.ends_at <= now:
            raise ApiError(409, "BOOKING_COMPLETED", "Completed bookings cannot be cancelled.")
        before = queries.booking(db, booking_id, now)
        row.status, row.cancelled_at = "cancelled", now
        db.flush()
        result = queries.booking(db, booking_id, now)
        audit(db, actor, booking_id, "admin.booking.cancelled", body, now, before, result)
        return result


def update_user(
    db: Session, actor: UUID, user_id: UUID, body: UserUpdate, now: datetime
) -> AdminUser:
    item = db.get(ApplicationUser, user_id)
    if item is None:
        raise ApiError(404, "USER_NOT_FOUND", "The user was not found.")
    revision(item.revision, body.revision)
    if item.role == "Admin" and item.is_active and (body.role != "Admin" or not body.is_active):
        count = (
            db.scalar(
                select(func.count())
                .select_from(ApplicationUser)
                .where(ApplicationUser.role == "Admin", ApplicationUser.is_active)
            )
            or 0
        )
        if count <= 1:
            raise ApiError(409, "LAST_ADMIN", "Keep at least one active administrator.")
    before = AdminUser.model_validate(item)
    if item.role != body.role or item.is_active != body.is_active:
        item.role, item.is_active = body.role, body.is_active
        item.revision += 1
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, refresh_owner=None, refresh_until=None)
        )
    result = AdminUser.model_validate(item)
    audit(db, actor, user_id, "admin.user.updated", body, now, before, result)
    return result
