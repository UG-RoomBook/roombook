"""HTTP room discovery endpoint."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.dependencies import get_session
from app.modules.availability.policy import current_time
from app.modules.rooms.availability import read_room, room_day
from app.modules.rooms.queries import list_rooms
from app.modules.rooms.schemas import (
    RoomAvailability,
    RoomDayAvailability,
    RoomDayQuery,
    RoomIntervalQuery,
    RoomList,
    RoomQuery,
    RoomRead,
)

router = APIRouter(prefix="/api/v1/rooms", tags=["rooms"])


@router.get(
    "",
    response_model=RoomList,
    operation_id="listRooms",
    responses={
        422: {"model": ErrorResponse, "description": "Invalid query parameters"},
        503: {"model": ErrorResponse, "description": "Database unavailable"},
    },
)
def get_rooms(
    query: Annotated[RoomQuery, Query()],
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(current_time)],
) -> RoomList:
    return list_rooms(session, now=now, **query.model_dump())


@router.get(
    "/{room_id}",
    response_model=RoomAvailability | RoomRead,
    operation_id="getRoom",
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def get_room(
    room_id: UUID,
    response: Response,
    query: Annotated[RoomIntervalQuery, Query()],
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(current_time)],
) -> RoomRead | RoomAvailability:
    response.headers["Cache-Control"] = "no-store"
    return read_room(session, room_id, now=now, **query.model_dump())


@router.get(
    "/{room_id}/availability",
    response_model=RoomDayAvailability,
    operation_id="getRoomDayAvailability",
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def get_room_day_availability(
    room_id: UUID,
    response: Response,
    query: Annotated[RoomDayQuery, Query()],
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(current_time)],
) -> RoomDayAvailability:
    response.headers["Cache-Control"] = "no-store"
    return room_day(session, room_id, day=query.day, now=now)
