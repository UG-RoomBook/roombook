import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, delete, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.availability.models import Closure, DateException, ExceptionHours, WeeklyHours
from app.modules.availability.policy import Interval
from app.modules.availability.service import load_calendars, locked_room, next_slots
from app.modules.bookings.models import Booking
from app.modules.rooms.models import Room

pytestmark = pytest.mark.database
NOW = datetime(2026, 10, 18, tzinfo=UTC)
START = datetime(2026, 10, 19, 2, tzinfo=UTC)  # Monday, 13:00 Melbourne.
END = START + timedelta(hours=1)


def add_room(session: Session) -> Room:
    room = Room(
        id=uuid4(), name=str(uuid4()), location="Synthetic", capacity=4, hours_confirmed=True
    )
    session.add(room)
    session.flush()
    session.add_all(
        WeeklyHours(room_id=room.id, weekday=day, start_minute=540, end_minute=1020)
        for day in range(7)
    )
    session.flush()
    return room


def add_booking(session: Session, room_id: UUID) -> None:
    session.add(Booking(room_id=room_id, starts_at=START, ends_at=END))


def add_closure(session: Session, room_id: UUID) -> None:
    session.add(
        Closure(room_id=room_id, starts_at=START, ends_at=END, reason="Synthetic maintenance")
    )


def test_calendar_reads_exceptions_closures_and_bookings(db_session: Session) -> None:
    room = add_room(db_session)
    cancelled = Booking(
        room_id=room.id, starts_at=START, ends_at=END, status="cancelled", cancelled_at=NOW
    )
    exception = DateException(room_id=room.id, date=date(2026, 10, 19))
    db_session.add_all([cancelled, exception])
    db_session.flush()
    slot = Interval(START, END)

    def loaded() -> bool:
        return load_calendars(db_session, [room], starts_at=START, ends_at=END)[room.id].available(
            slot
        )

    assert not loaded()  # Empty exception closes the whole day.
    db_session.add(ExceptionHours(exception_id=exception.id, start_minute=780, end_minute=840))
    assert loaded()  # Overrides the default; cancelled reservations don't block.
    add_closure(db_session, room.id)
    assert not loaded()
    db_session.execute(delete(Closure))
    add_booking(db_session, room.id)
    assert not loaded()


def test_next_slots_reads_one_bounded_batch(db_session: Session, db_engine: Engine) -> None:
    rooms = [add_room(db_session) for _ in range(25)]
    add_booking(db_session, rooms[0].id)
    db_session.flush()
    statements: list[str] = []

    def record(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.startswith("SELECT"):
            statements.append(statement)

    event.listen(db_engine, "before_cursor_execute", record)
    try:
        result = next_slots(
            db_session, rooms, duration=timedelta(hours=1), now=NOW, not_before=START
        )
    finally:
        event.remove(db_engine, "before_cursor_execute", record)
    assert result[rooms[0].id] == Interval(END, END + timedelta(hours=1))
    assert result[rooms[1].id] == Interval(START, END)
    assert len(statements) == 4
    assert next_slots(db_session, [], duration=timedelta(hours=1), now=NOW) == {}
    with pytest.raises(ValueError, match="100"):
        load_calendars(db_session, rooms * 5, starts_at=START, ends_at=END)


@pytest.mark.parametrize("mutation", ["closure", "hours", "exception", "deactivate", "unconfirm"])
def test_mutations_cannot_invalidate_bookings(
    db_engine: Engine, clean_database: None, mutation: str
) -> None:
    with Session(db_engine) as session, session.begin():
        room_id = add_room(session).id
        add_booking(session, room_id)
    with Session(db_engine) as session:
        with (
            pytest.raises(ApiError) as caught,
            locked_room(session, room_id, clock=lambda: NOW) as guard,
        ):
            if mutation == "closure":
                add_closure(session, room_id)
            elif mutation == "hours":
                session.execute(delete(WeeklyHours).where(WeeklyHours.room_id == room_id))
            elif mutation == "exception":
                session.add(DateException(room_id=room_id, date=date(2026, 10, 19)))
            elif mutation == "deactivate":
                guard.room.active = False
            else:
                guard.room.hours_confirmed = False
        assert caught.value.code == "BOOKINGS_AFFECTED"
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 1
        assert session.scalar(select(func.count()).select_from(Closure)) == 0
        room = session.get(Room, room_id)
        assert room is not None and room.active and room.hours_confirmed
        assert load_calendars(session, [room], starts_at=START, ends_at=END)[room_id].supports(
            Interval(START, END)
        )


def test_ongoing_and_legacy_policy_bookings_are_preserved(
    db_engine: Engine, clean_database: None
) -> None:
    with Session(db_engine) as session, session.begin():
        room_id = add_room(session).id
        # A pre-policy three-hour booking need not meet new duration rules.
        session.add(Booking(room_id=room_id, starts_at=START, ends_at=START + timedelta(hours=3)))
    with Session(db_engine) as session:
        with locked_room(session, room_id, clock=lambda: START + timedelta(hours=1)):
            session.add(
                Closure(
                    room_id=room_id,
                    starts_at=END + timedelta(hours=2),
                    ends_at=END + timedelta(hours=3),
                    reason="Adjacent",
                )
            )
        with (
            pytest.raises(ApiError, match="Resolve"),
            locked_room(session, room_id, clock=lambda: START + timedelta(hours=1)) as guard,
        ):
            guard.room.active = False
        # Completed history does not prevent deactivation, and stays stored.
        with locked_room(session, room_id, clock=lambda: START + timedelta(days=1)) as guard:
            guard.room.active = False
        assert session.scalar(select(func.count()).select_from(Booking)) == 1


def test_transaction_guard_and_booking_recheck(db_engine: Engine, clean_database: None) -> None:
    with Session(db_engine) as session, session.begin():
        room_id = add_room(session).id
    with Session(db_engine) as session:
        with locked_room(session, room_id, clock=lambda: NOW) as guard:
            assert guard.require_available(START, END) == Interval(START, END)
            add_booking(session, room_id)
        with pytest.raises(RuntimeError, match="original transaction"):
            guard.require_available(START, END)
        with (
            pytest.raises(ApiError) as caught,
            locked_room(session, room_id, clock=lambda: NOW) as guard,
        ):
            guard.require_available(START, END)
        assert caught.value.code == "ROOM_UNAVAILABLE"
        with pytest.raises(ApiError) as missing, locked_room(session, uuid4()):
            pass
        assert missing.value.status_code == 404
        with (
            session.begin(),
            pytest.raises(RuntimeError, match="clean session"),
            locked_room(session, room_id),
        ):
            pass
    with db_engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with Session(connection) as session, pytest.raises(RuntimeError, match="READ COMMITTED"):
            with locked_room(session, room_id):
                pass


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("closure", "booking", "ROOM_UNAVAILABLE"),
        ("booking", "closure", "BOOKINGS_AFFECTED"),
        ("booking", "booking", "ROOM_UNAVAILABLE"),
    ],
)
def test_two_connections_serialize_on_room_and_recheck_after_commit(
    db_engine: Engine, clean_database: None, first: str, second: str, expected: str
) -> None:
    with Session(db_engine) as session, session.begin():
        room_id = add_room(session).id
    waiting = Event()
    waiter_pid: list[int] = []

    def write(session: Session, action: str) -> None:
        with locked_room(session, room_id, clock=lambda: NOW) as guard:
            if action == "booking":
                guard.require_available(START, END)
                add_booking(session, room_id)
            else:
                add_closure(session, room_id)

    def contender() -> str:
        with db_engine.connect() as connection, Session(connection) as session:
            driver = connection.connection.driver_connection
            assert driver is not None
            waiter_pid.append(driver.info.backend_pid)
            waiting.set()
            try:
                write(session, second)
            except ApiError as error:
                return error.code
            return "committed"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with (
            Session(db_engine) as session,
            locked_room(session, room_id, clock=lambda: NOW) as guard,
        ):
            if first == "booking":
                guard.require_available(START, END)
                add_booking(session, room_id)
            else:
                add_closure(session, room_id)
            session.flush()
            future = executor.submit(contender)
            assert waiting.wait(timeout=5)
            deadline = time.monotonic() + 5
            with db_engine.connect() as observer:
                while time.monotonic() < deadline:
                    blockers = observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": waiter_pid[0]}
                    )
                    if blockers:
                        break
                    time.sleep(0.01)
                else:
                    pytest.fail("The competing writer never waited on the room row")
            assert not future.done()
        assert future.result(timeout=5) == expected
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == (first == "booking")
        assert session.scalar(select(func.count()).select_from(Closure)) == (first == "closure")


@pytest.mark.parametrize(
    "values",
    [
        {"weekday": -1},
        {"weekday": 7},
        {"start_minute": -1},
        {"end_minute": 1441},
        {"start_minute": 600, "end_minute": 600},
        {"start_minute": 600, "end_minute": 660},
    ],
)
def test_database_rejects_invalid_or_overlapping_hours(
    db_session: Session, values: dict[str, int]
) -> None:
    room = add_room(db_session)
    data = {"weekday": 0, "start_minute": 540, "end_minute": 1020, **values}
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(WeeklyHours(room_id=room.id, **data))
        db_session.flush()


def test_database_rejects_duplicate_exceptions_overlapping_windows_and_bad_closures(
    db_session: Session,
) -> None:
    room = add_room(db_session)
    exception = DateException(room_id=room.id, date=date(2026, 10, 19))
    db_session.add(exception)
    db_session.flush()
    db_session.add(ExceptionHours(exception_id=exception.id, start_minute=540, end_minute=600))
    db_session.flush()
    for invalid in (
        DateException(room_id=room.id, date=exception.date),
        ExceptionHours(exception_id=exception.id, start_minute=570, end_minute=630),
        Closure(room_id=room.id, starts_at=START, ends_at=START, reason="Invalid"),
        Closure(room_id=room.id, starts_at=START, ends_at=END, reason=" "),
    ):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(invalid)
            db_session.flush()
    # Adjacent windows are safe.
    db_session.add(ExceptionHours(exception_id=exception.id, start_minute=600, end_minute=660))
    db_session.flush()
