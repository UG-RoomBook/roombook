from datetime import date, datetime
from typing import Annotated, Any, Literal, Self, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.availability.policy import CAMPUS, local_instant

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
T = TypeVar("T")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


class PageQuery(Input):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class ReasonInput(Input):
    reason: Reason


class RoomCreate(ReasonInput):
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=200)
    capacity: int = Field(gt=0, le=1000)


class RoomUpdate(RoomCreate):
    kind: Literal["room"] = "room"
    revision: int = Field(ge=1)
    active: bool


class AdminRoom(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    location: str
    capacity: int
    active: bool
    hours_confirmed: bool
    revision: int


class HoursInput(Input):
    start_minute: int = Field(ge=0, lt=1440, multiple_of=15)
    end_minute: int = Field(gt=0, le=1440, multiple_of=15)

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.start_minute >= self.end_minute:
            raise ValueError("Opening time must precede closing time.")
        return self


def no_overlap(windows: list[HoursInput]) -> None:
    ordered = sorted(windows, key=lambda window: window.start_minute)
    if any(a.end_minute > b.start_minute for a, b in zip(ordered, ordered[1:], strict=False)):
        raise ValueError("Opening windows must not overlap.")


class WeeklyInput(HoursInput):
    weekday: int = Field(ge=0, le=6)


class ExceptionInput(Input):
    date: date
    windows: list[HoursInput] = Field(max_length=16)

    @model_validator(mode="after")
    def valid_windows(self) -> Self:
        no_overlap(self.windows)
        return self


class ClosureInput(Input):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: Reason

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.starts_at >= self.ends_at:
            raise ValueError("Closure start must precede its end.")
        for instant in (self.starts_at, self.ends_at):
            local_instant(instant.astimezone(CAMPUS).replace(tzinfo=None))
        return self


class ScheduleData(Input):
    hours_confirmed: bool
    weekly: list[WeeklyInput] = Field(max_length=112)
    exceptions: list[ExceptionInput] = Field(max_length=366)
    closures: list[ClosureInput] = Field(max_length=500)

    @model_validator(mode="after")
    def unique_windows(self) -> Self:
        if len({item.date for item in self.exceptions}) != len(self.exceptions):
            raise ValueError("Use one exception per date.")
        for day in range(7):
            no_overlap([item for item in self.weekly if item.weekday == day])
        return self


class ScheduleUpdate(ScheduleData, ReasonInput):
    kind: Literal["schedule"] = "schedule"
    revision: int = Field(ge=1)


class ScheduleRead(ScheduleData):
    room_id: UUID
    revision: int
    timezone: Literal["Australia/Melbourne"] = "Australia/Melbourne"


class AdminUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    verified_email: str | None
    email_checked_at: datetime | None
    role: Literal["Member", "Admin"]
    is_active: bool
    revision: int
    created_at: datetime


class UserUpdate(ReasonInput):
    revision: int = Field(ge=1)
    role: Literal["Member", "Admin"]
    is_active: bool


class AdminBooking(BaseModel):
    id: UUID
    room_id: UUID
    room_name: str
    owner_id: UUID | None
    owner_label: str
    starts_at: datetime
    ends_at: datetime
    created_at: datetime
    cancelled_at: datetime | None
    status: Literal["Upcoming", "Ongoing", "Completed", "Cancelled"]


class BookingPage(Page[AdminBooking]):
    generated_at: datetime


class Activity(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    actor_label: str
    target_id: UUID | None
    action: str
    occurred_at: datetime
    details: dict[str, Any]


class Impact(BaseModel):
    revision: int
    affected_count: int
    affected_bookings: list[AdminBooking]
    generated_at: datetime


class Overview(BaseModel):
    generated_at: datetime
    timezone: Literal["Australia/Melbourne"] = "Australia/Melbourne"
    active_rooms: int
    active_users: int
    bookings_today: int
    unconfirmed_rooms: int
    agenda: list[AdminBooking]
    recent_activity: list[Activity]
