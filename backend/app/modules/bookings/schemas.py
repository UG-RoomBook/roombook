"""Booking-create contract; owner and status are server controlled."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator


class BookingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    room_id: UUID
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @field_validator("starts_at", "ends_at", mode="before")
    @classmethod
    def parse_timestamp(cls, value: object) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime):
            raise ValueError("Use an ISO 8601 timestamp with an explicit offset.")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Include a timezone offset.")
        try:
            return value.astimezone(UTC)
        except OverflowError as exc:
            raise ValueError("Use timestamps within the supported UTC range.") from exc


class BookingCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    room_id: UUID
    owner_id: UUID
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    status: Literal["active"] = "active"
    created_at: AwareDatetime
