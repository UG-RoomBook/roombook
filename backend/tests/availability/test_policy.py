from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.errors import ApiError
from app.modules.availability.policy import (
    CAMPUS,
    HORIZON,
    Calendar,
    Hours,
    Interval,
    local_instant,
    next_slot,
    validate_slot,
)

NOW = datetime(2026, 10, 18, 2, tzinfo=UTC)
START = NOW + timedelta(days=1)


def calendar() -> Calendar:
    return Calendar(True, True, {day: [Hours(540, 1020)] for day in range(7)}, {}, [], [])


@pytest.mark.parametrize("minutes", [30, 31, 120])
def test_inclusive_duration_and_start_horizon(minutes: int) -> None:
    for start in (NOW + timedelta(minutes=15), NOW + HORIZON):
        slot = validate_slot(start, start + timedelta(minutes=minutes), now=NOW)
        assert slot.starts_at == start


@pytest.mark.parametrize(
    ("start", "duration"),
    [
        (NOW, 60),
        (NOW - timedelta(minutes=15), 60),
        (NOW + HORIZON + timedelta(minutes=15), 60),
        (START, 29),
        (START, 121),
        (START, -30),
        (START + timedelta(minutes=1), 60),
        (START + timedelta(seconds=1), 60),
        (START + timedelta(microseconds=1), 60),
        (START.replace(tzinfo=None), 60),
    ],
)
def test_invalid_policy(start: datetime, duration: int) -> None:
    with pytest.raises(ApiError) as caught:
        validate_slot(start, start + timedelta(minutes=duration), now=NOW)
    assert caught.value.status_code == 422
    assert caught.value.details


@pytest.mark.parametrize("wall", ["2026-04-05T02:30:00", "2026-10-04T02:30:00"])
def test_ambiguous_and_nonexistent_campus_times_are_rejected(wall: str) -> None:
    with pytest.raises(ApiError, match="DST"):
        local_instant(datetime.fromisoformat(wall))


def test_local_resolution_requires_naive_input() -> None:
    with pytest.raises(ValueError):
        local_instant(NOW)


@pytest.mark.parametrize(
    ("start", "end", "minutes"),
    [
        ("2026-10-04T01:30:00", "2026-10-04T03:00:00", 30),
        ("2026-04-05T01:30:00", "2026-04-05T03:00:00", 150),
    ],
)
def test_duration_is_elapsed_time_across_dst(start: str, end: str, minutes: int) -> None:
    first, last = (
        local_instant(datetime.fromisoformat(start)),
        local_instant(datetime.fromisoformat(end)),
    )
    assert (last - first).total_seconds() == minutes * 60
    if minutes > 120:
        with pytest.raises(ApiError, match="duration"):
            validate_slot(first, last, now=first - timedelta(days=1))
    else:
        assert validate_slot(first, last, now=first - timedelta(days=1)).ends_at == last


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-04-05T02:30:00+11:00", "2026-04-05T03:00:00+10:00"),
        ("2026-04-04T15:30:00Z", "2026-04-04T17:00:00Z"),
        ("2026-04-05T01:30:00+11:00", "2026-04-05T02:00:00+11:00"),
    ],
)
def test_ambiguous_endpoints_are_rejected_even_with_offsets(start: str, end: str) -> None:
    with pytest.raises(ApiError, match="DST"):
        validate_slot(
            datetime.fromisoformat(start),
            datetime.fromisoformat(end),
            now=datetime(2026, 4, 4, tzinfo=UTC),
        )


def test_complete_interval_must_fit_hours_and_half_open_blockers() -> None:
    source = calendar()
    opening = local_instant(datetime(2026, 10, 19, 9))
    closing = local_instant(datetime(2026, 10, 19, 17))
    assert source.available(Interval(opening, closing))
    assert not source.available(Interval(opening - timedelta(minutes=15), opening))
    assert not source.available(
        Interval(closing - timedelta(minutes=30), closing + timedelta(minutes=1))
    )
    source.closures = [Interval(START, START + timedelta(hours=1))]
    assert source.available(Interval(START - timedelta(hours=1), START))
    assert source.available(Interval(START + timedelta(hours=1), START + timedelta(hours=2)))
    assert not source.available(
        Interval(START - timedelta(minutes=15), START + timedelta(minutes=15))
    )
    source.closures = []
    source.bookings = [Interval(START, START + timedelta(hours=1))]
    assert not source.available(Interval(START, START + timedelta(minutes=30)))
    assert source.supports(Interval(START, START + timedelta(minutes=30)))


def test_date_exception_replaces_weekly_windows_including_closed_day() -> None:
    source = calendar()
    day = START.astimezone(CAMPUS).date()
    source.exceptions[day] = []
    assert not source.available(Interval(START, START + timedelta(minutes=30)))
    source.exceptions[day] = [Hours(780, 810)]
    assert source.available(Interval(START, START + timedelta(minutes=30)))
    assert not source.available(Interval(START, START + timedelta(minutes=45)))


def test_adjacent_windows_and_midnight_are_contiguous_but_gaps_are_closed() -> None:
    source = Calendar(
        True, True, {day: [Hours(0, 720), Hours(720, 1440)] for day in range(7)}, {}, [], []
    )
    midnight = local_instant(datetime(2026, 10, 20))
    slot = Interval(midnight - timedelta(minutes=30), midnight + timedelta(minutes=30))
    assert source.available(slot)
    source.exceptions[date(2026, 10, 20)] = [Hours(15, 1440)]
    assert not source.available(slot)


def test_inactive_unconfirmed_and_invalid_intervals_fail_closed() -> None:
    source = calendar()
    slot = Interval(START, START + timedelta(minutes=30))
    source.active = False
    assert not source.available(slot)
    source.active, source.confirmed = True, False
    assert not source.available(slot)
    source.confirmed = True
    assert not source.available(Interval(START, START))


def test_dst_schedule_boundary_fails_closed() -> None:
    assert Hours(120, 180).on(date(2026, 10, 4)) is None
    assert Hours(120, 180).on(date(2026, 4, 5)) is None
    assert Hours(0, 1440).on(date(2026, 10, 4)) is not None


def test_next_slot_rounds_forward_fits_duration_and_stops_at_horizon() -> None:
    source = calendar()
    source.bookings = [Interval(NOW, NOW + timedelta(minutes=31))]
    slot = next_slot(source, duration=timedelta(minutes=30), now=NOW)
    assert slot == Interval(NOW + timedelta(minutes=45), NOW + timedelta(minutes=75))
    lower = NOW + timedelta(minutes=45)
    assert next_slot(source, duration=timedelta(minutes=30), now=NOW, not_before=lower) == slot
    assert (
        next_slot(
            source,
            duration=timedelta(hours=1),
            now=NOW,
            not_before=NOW + HORIZON + timedelta(seconds=1),
        )
        is None
    )
    source.confirmed = False
    assert next_slot(source, duration=timedelta(hours=1), now=NOW) is None
    with pytest.raises(ApiError):
        next_slot(source, duration=timedelta(minutes=15), now=NOW)


def test_next_slot_skips_repeated_endpoints() -> None:
    source = Calendar(True, True, {6: [Hours(0, 1440)]}, {}, [], [])
    now = local_instant(datetime(2026, 4, 5, 1, 45))
    assert next_slot(source, duration=timedelta(minutes=30), now=now) == Interval(
        local_instant(datetime(2026, 4, 5, 3)), local_instant(datetime(2026, 4, 5, 3, 30))
    )


def test_next_slot_has_no_result_for_insufficient_window_and_horizon_exhaustion() -> None:
    source = Calendar(True, True, {day: [Hours(540, 570)] for day in range(7)}, {}, [], [])
    assert next_slot(source, duration=timedelta(hours=1), now=NOW) is None
    source.weekly = {day: [Hours(0, 1440)] for day in range(7)}
    slot = next_slot(source, duration=timedelta(hours=2), now=NOW, not_before=NOW + HORIZON)
    assert slot == Interval(NOW + HORIZON, NOW + HORIZON + timedelta(hours=2))
    source.closures = [Interval(NOW, NOW + HORIZON + timedelta(hours=2))]
    assert next_slot(source, duration=timedelta(minutes=30), now=NOW) is None


def test_next_slot_crosses_spring_gap_using_elapsed_duration() -> None:
    source = Calendar(True, True, {6: [Hours(0, 1440)]}, {}, [], [])
    now = local_instant(datetime(2026, 10, 4, 1, 45))
    assert next_slot(source, duration=timedelta(minutes=30), now=now) == Interval(
        local_instant(datetime(2026, 10, 4, 3)), local_instant(datetime(2026, 10, 4, 3, 30))
    )
