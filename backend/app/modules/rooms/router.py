"""HTTP room discovery endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.errors import ErrorResponse
from app.dependencies import get_session
from app.modules.rooms.queries import list_rooms
from app.modules.rooms.schemas import RoomList, RoomQuery

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
) -> RoomList:
    return list_rooms(session, **query.model_dump())
