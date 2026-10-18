"""Room discovery inputs and public response shapes."""

from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class RoomQuery(BaseModel):
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=9_223_372_036_854_775_807)

    @field_validator("starts_at", "ends_at", mode="before")
    @classmethod
    def parse_timestamp(cls, value: object) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError("Use an ISO 8601 timestamp with an explicit offset.")
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Use an ISO 8601 timestamp with an explicit offset.") from exc

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if (self.starts_at is None) != (self.ends_at is None):
            raise ValueError("Provide starts_at and ends_at together.")
        if self.starts_at is not None and self.ends_at is not None:
            try:
                self.starts_at = self.starts_at.astimezone(UTC)
                self.ends_at = self.ends_at.astimezone(UTC)
            except OverflowError as exc:
                raise ValueError("Use timestamps within the supported UTC range.") from exc
            if self.starts_at >= self.ends_at:
                raise ValueError("starts_at must be before ends_at.")
        return self


class RoomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    location: str
    capacity: int = Field(gt=0)
    active: bool


class RoomAvailability(RoomRead):
    available: bool


class RoomList(BaseModel):
    # Separate shapes keep availability absent for metadata and boolean for intervals.
    items: list[RoomAvailability | RoomRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
