"""Atomic owned booking creation and durable retry reconciliation."""

import hashlib
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.availability.policy import current_time
from app.modules.availability.service import room_in_transaction
from app.modules.bookings.models import Booking, BookingRequest
from app.modules.bookings.schemas import BookingCreate, BookingCreated
from app.modules.identity.models import ApplicationUser, AuditEvent


def request_lock_id(user_id: UUID, key: UUID) -> int:
    """A collision can only cause a transient busy response, never share results."""
    digest = hashlib.sha256(b"booking-create:" + user_id.bytes + key.bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def create_booking(
    session: Session,
    *,
    user_id: UUID,
    key: UUID,
    body: BookingCreate,
    clock: Callable[[], datetime] = current_time,
) -> BookingCreated:
    """user_id must come from a verified standard session, never request JSON.

    Lock order: per-user/key advisory lock, active user shared lock, room row.
    One commit includes booking, original response, and audit. Failures roll back
    the key too. Replays are checked before time/calendar validation so a lost
    response remains recoverable after the slot has passed or been cancelled.
    """
    if session.in_transaction() or session.new or session.dirty or session.deleted:
        raise RuntimeError("Use a clean session; create_booking owns the transaction")
    payload_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    try:
        with session.begin():
            if session.connection().get_isolation_level() != "READ COMMITTED":
                raise RuntimeError("Booking writers require READ COMMITTED isolation")
            acquired = session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": request_lock_id(user_id, key)},
            )
            if not acquired:
                raise ApiError(
                    409,
                    "REQUEST_IN_PROGRESS",
                    "Retry the same request and key after a short delay.",
                )
            user = session.scalar(
                select(ApplicationUser)
                .where(ApplicationUser.id == user_id)
                .with_for_update(read=True)
            )
            if user is None or not user.is_active:
                raise ApiError(403, "ACCOUNT_INACTIVE", "This account cannot create bookings.")
            previous = session.get(BookingRequest, (user_id, key))
            if previous is not None:
                if previous.payload_hash != payload_hash:
                    raise ApiError(
                        409, "IDEMPOTENCY_MISMATCH", "This key was used for a different request."
                    )
                result = BookingCreated.model_validate(previous.result)
            else:
                with room_in_transaction(session, body.room_id, clock=clock) as guard:
                    slot = guard.require_available(body.starts_at, body.ends_at)
                    booking = Booking(
                        owner_id=user_id,
                        room_id=body.room_id,
                        starts_at=slot.starts_at,
                        ends_at=slot.ends_at,
                    )
                    session.add(booking)
                    session.flush()
                    result = BookingCreated.model_validate(booking)
                    session.add(
                        BookingRequest(
                            user_id=user_id,
                            key=key,
                            payload_hash=payload_hash,
                            booking_id=booking.id,
                            result=result.model_dump(mode="json"),
                        )
                    )
                    session.add(
                        AuditEvent(
                            actor_user_id=user_id, action="booking.created", target_id=booking.id
                        )
                    )
        return result
    except IntegrityError as exc:
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == (
            "bookings_active_room_interval_excl"
        ):
            raise ApiError(
                409, "ROOM_UNAVAILABLE", "The room is unavailable for this interval."
            ) from None
        raise
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "40P01", "40001"}:
            raise ApiError(
                409, "BOOKING_BUSY", "Retry the same request and key after a short delay."
            ) from None
        raise
