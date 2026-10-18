from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.rooms.schemas import RoomAvailability, RoomList, RoomQuery, RoomRead


@pytest.mark.parametrize(
    "parameters",
    [
        {"starts_at": "2026-10-19T13:00:00+11:00"},
        {"ends_at": "2026-10-19T14:00:00+11:00"},
        {"starts_at": "2026-10-19T13:00:00", "ends_at": "2026-10-19T14:00:00+11:00"},
        {"starts_at": "2026-10-19T13:00:00+11:00", "ends_at": "2026-10-19T14:00:00"},
        {
            "starts_at": "2026-10-19T14:00:00+11:00",
            "ends_at": "2026-10-19T14:00:00+11:00",
        },
        {
            "starts_at": "2026-10-19T15:00:00+11:00",
            "ends_at": "2026-10-19T14:00:00+11:00",
        },
        {"starts_at": "1792375200", "ends_at": "1792378800"},
        {"starts_at": 1792375200, "ends_at": 1792378800},
        {"starts_at": "invalid", "ends_at": "2026-10-19T14:00:00+11:00"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"offset": 9_223_372_036_854_775_808},
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
def test_invalid_room_queries_are_rejected(parameters: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RoomQuery.model_validate(parameters)


def test_query_uses_utc_instants_across_dst_transition() -> None:
    query = RoomQuery.model_validate(
        {
            "starts_at": "2026-04-05T02:30:00+11:00",
            "ends_at": "2026-04-05T02:00:00+10:00",
        }
    )

    assert query.starts_at == datetime(2026, 4, 4, 15, 30, tzinfo=UTC)
    assert query.ends_at == datetime(2026, 4, 4, 16, 0, tzinfo=UTC)


def test_default_query_does_not_invent_an_interval() -> None:
    assert RoomQuery().model_dump() == {
        "starts_at": None,
        "ends_at": None,
        "limit": 20,
        "offset": 0,
    }


def test_room_response_omits_unknown_availability_and_keeps_false() -> None:
    fields = {
        "id": UUID("10000000-0000-4000-8000-000000000001"),
        "name": "Studio",
        "location": "West Wing",
        "capacity": 4,
        "active": True,
    }
    metadata = RoomRead.model_validate(fields)
    unavailable = RoomAvailability(**metadata.model_dump(), available=False)

    result = RoomList(items=[metadata, unavailable], total=2, limit=20, offset=0).model_dump()

    assert "available" not in result["items"][0]
    assert result["items"][1]["available"] is False
