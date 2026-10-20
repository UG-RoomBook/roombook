"""ADR-009: UTC instants, Melbourne calendar rules and explicit DST rejection."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.errors import ApiError, ValidationDetail

CAMPUS = ZoneInfo("Australia/Melbourne")
STEP = timedelta(minutes=15)
HORIZON = timedelta(days=14)
MIN_DURATION = timedelta(minutes=30)
MAX_DURATION = timedelta(hours=2)


def current_time() -> datetime:
    return datetime.now(UTC)


def invalid_slot(message: str) -> ApiError:
    return ApiError(
        422,
        "VALIDATION_ERROR",
        message,
        [ValidationDetail(field="query.interval", code="booking_policy", message=message)],
    )


def local_instant(value: datetime) -> datetime:
    """Resolve a naive campus time only when exactly one UTC instant exists."""
    if value.tzinfo is not None:
        raise ValueError("Expected a naive campus time")
    candidates = {
        candidate
        for fold in (0, 1)
        if (candidate := value.replace(tzinfo=CAMPUS, fold=fold).astimezone(UTC))
        .astimezone(CAMPUS)
        .replace(tzinfo=None)
        == value
    }
    if len(candidates) != 1:
        raise invalid_slot("Choose a Melbourne time outside the skipped or repeated DST hour.")
    return candidates.pop()


def utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise invalid_slot("Include a timezone offset.")
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise invalid_slot("Use a supported timestamp.") from exc


@dataclass(frozen=True)
class Interval:
    starts_at: datetime
    ends_at: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.starts_at < other.ends_at and self.ends_at > other.starts_at


def validate_duration(duration: timedelta) -> None:
    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise invalid_slot("Choose a duration from 30 minutes to two hours.")


def validate_slot(starts_at: datetime, ends_at: datetime, *, now: datetime) -> Interval:
    start, end, clock = utc(starts_at), utc(ends_at), utc(now)
    if not clock < start <= clock + HORIZON:
        raise invalid_slot("Choose a future start no more than 14 days ahead.")
    validate_duration(end - start)
    local_start = start.astimezone(CAMPUS)
    if local_start.minute % 15 or local_start.second or local_start.microsecond:
        raise invalid_slot("Choose a start on a 15-minute Melbourne time boundary.")
    # UTC and offset representations receive the same answer. Repeated endpoints
    # remain forbidden even when the caller supplied a disambiguating offset.
    for instant in (start, end):
        local_instant(instant.astimezone(CAMPUS).replace(tzinfo=None))
    return Interval(start, end)


@dataclass(frozen=True, order=True)
class Hours:
    start_minute: int
    end_minute: int

    def on(self, day: date) -> Interval | None:
        midnight = datetime.combine(day, time())
        try:
            return Interval(
                local_instant(midnight + timedelta(minutes=self.start_minute)),
                local_instant(midnight + timedelta(minutes=self.end_minute)),
            )
        except ApiError:
            # A recurring boundary landing inside a DST gap/fold fails closed.
            return None


@dataclass
class Calendar:
    active: bool
    confirmed: bool
    weekly: dict[int, list[Hours]]
    exceptions: dict[date, list[Hours]]
    closures: list[Interval]
    bookings: list[Interval]

    def supports(self, slot: Interval) -> bool:
        """Calendar-only check also preserves legacy bookings outside new policy."""
        if not self.active or not self.confirmed or slot.starts_at >= slot.ends_at:
            return False
        if any(slot.overlaps(closure) for closure in self.closures):
            return False
        day = slot.starts_at.astimezone(CAMPUS).date()
        last = slot.ends_at.astimezone(CAMPUS).date()
        covered = slot.starts_at
        while day <= last:
            for hours in sorted(self.exceptions.get(day, self.weekly.get(day.weekday(), []))):
                window = hours.on(day)
                if window is None or window.ends_at <= covered:
                    continue
                if window.starts_at > covered:
                    return False
                covered = window.ends_at
                if covered >= slot.ends_at:
                    return True
            if day == last:
                break
            day += timedelta(days=1)
        return False

    def available(self, slot: Interval) -> bool:
        return self.supports(slot) and not any(slot.overlaps(item) for item in self.bookings)


def next_slot(
    calendar: Calendar, *, duration: timedelta, now: datetime, not_before: datetime | None = None
) -> Interval | None:
    """At most 1,345 candidates, no database queries and a clear no-slot result."""
    validate_duration(duration)
    if not calendar.active or not calendar.confirmed:
        return None
    clock = utc(now)
    lower = max(clock, utc(not_before) if not_before is not None else clock)
    # Melbourne offsets are multiples of 15 minutes throughout this horizon.
    candidate = lower.replace(second=0, microsecond=0)
    candidate -= timedelta(minutes=candidate.minute % 15)
    if candidate < lower or candidate <= clock:
        candidate += STEP
    while candidate <= clock + HORIZON:
        try:
            slot = validate_slot(candidate, candidate + duration, now=clock)
        except ApiError:
            pass
        else:
            if calendar.available(slot):
                return slot
        candidate += STEP
    return None
