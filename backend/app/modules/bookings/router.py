from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.dependencies import get_session
from app.modules.bookings.schemas import BookingCreate, BookingCreated
from app.modules.bookings.service import create_booking
from app.modules.identity.dependencies import require_booking_session
from app.modules.identity.service import SessionResult

router = APIRouter(prefix="/api/v1/bookings", tags=["Bookings"])


@router.post(
    "",
    operation_id="createBooking",
    status_code=201,
    response_model=BookingCreated,
    description=(
        "Create a booking owned by the authenticated user. A required UUID Idempotency-Key "
        "is scoped to that user and retained with booking history without automatic expiry. "
        "The same normalized request replays the original 201 body, including after cancellation. "
        "A changed payload returns IDEMPOTENCY_MISMATCH. REQUEST_IN_PROGRESS or BOOKING_BUSY "
        "means retry the same key and payload after a short delay. After timeout or 503, reconcile "
        "by repeating the same key and payload; never generate a new key for an uncertain result. "
        "Validation/conflict failures roll back and do not consume the key."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Sign-in required"},
        403: {"model": ErrorResponse, "description": "Restricted account or invalid Origin/CSRF"},
        404: {"model": ErrorResponse, "description": "Room not found"},
        409: {
            "model": ErrorResponse,
            "description": "Room unavailable, key mismatch or transient busy",
        },
        422: {"model": ErrorResponse, "description": "Invalid body, key or booking interval"},
        503: {"model": ErrorResponse, "description": "Database or account services unavailable"},
    },
)
def book(
    body: BookingCreate,
    identity: Annotated[SessionResult, Depends(require_booking_session)],
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[
        UUID, Header(description="Persist one UUID per logical booking attempt.")
    ],
) -> BookingCreated:
    return create_booking(session, user_id=identity.user_id, key=idempotency_key, body=body)
