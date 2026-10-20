from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.availability.models import Closure
from app.modules.availability.service import locked_room, room_in_transaction
from app.modules.bookings.models import Booking, BookingRequest
from app.modules.bookings.schemas import BookingCreate, BookingCreated
from app.modules.bookings.service import create_booking, request_lock_id
from app.modules.identity.models import ApplicationUser, AuditEvent
from tests.availability.test_service import END, NOW, START, add_room

pytestmark = pytest.mark.database


@pytest.fixture
def owned_room(db_engine: Engine, clean_database: None) -> tuple[UUID, UUID, BookingCreate]:
    with Session(db_engine) as session, session.begin():
        user, other = ApplicationUser(id=uuid4()), ApplicationUser(id=uuid4())
        session.add_all([user, other])
        body = BookingCreate(room_id=add_room(session).id, starts_at=START, ends_at=END)
        return user.id, other.id, body


def create(engine: Engine, user: UUID, key: UUID, body: BookingCreate) -> BookingCreated:
    with Session(engine) as session:
        return create_booking(session, user_id=user, key=key, body=body, clock=lambda: NOW)


def counts(engine: Engine) -> tuple[int | None, ...]:
    with Session(engine) as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Booking, BookingRequest, AuditEvent)
        )


def test_commits_owner_result_and_audit_then_replays_after_cancellation(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate]
) -> None:
    user, _, body = owned_room
    key = uuid4()
    result = create(db_engine, user, key, body)
    assert result.owner_id == user and result.status == "active"
    with Session(db_engine) as session, session.begin():
        booking = session.get(Booking, result.id)
        assert booking is not None and booking.owner_id == user
        booking.status, booking.cancelled_at = "cancelled", NOW
    # Normalize offset and UUID spelling; replay after start/horizon validation would fail.
    normalized = BookingCreate.model_validate(
        {
            "room_id": str(body.room_id).upper(),
            "starts_at": "2026-10-19T13:00:00+11:00",
            "ends_at": "2026-10-19T14:00:00+11:00",
        }
    )
    with Session(db_engine) as session:
        replay = create_booking(session, user_id=user, key=key, body=normalized, clock=lambda: END)
    assert replay == result and counts(db_engine) == (1, 1, 1)


def test_key_scope_mismatch_cross_user_and_adjacent_intervals(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate]
) -> None:
    user, other, body = owned_room
    key = uuid4()
    first = create(db_engine, user, key, body)
    adjacent = body.model_copy(update={"starts_at": END, "ends_at": END + timedelta(hours=1)})
    with pytest.raises(ApiError) as mismatch:
        create(db_engine, user, key, adjacent)
    assert mismatch.value.code == "IDEMPOTENCY_MISMATCH"
    with pytest.raises(ApiError) as overlap:
        create(db_engine, other, key, body)
    assert overlap.value.code == "ROOM_UNAVAILABLE" and str(first.id) not in str(overlap.value)
    second = create(db_engine, other, key, adjacent)
    assert second.owner_id == other and second.id != first.id
    assert counts(db_engine) == (2, 2, 2)


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing", "ROOM_NOT_FOUND"),
        ("past", "VALIDATION_ERROR"),
        ("inactive", "ROOM_UNAVAILABLE"),
        ("unconfirmed", "ROOM_UNAVAILABLE"),
        ("user", "ACCOUNT_INACTIVE"),
        ("unknown_user", "ACCOUNT_INACTIVE"),
    ],
)
def test_failed_attempts_do_not_consume_keys_or_write_bookings(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate], case: str, code: str
) -> None:
    user, _, body = owned_room
    key = uuid4()
    if case == "missing":
        body = body.model_copy(update={"room_id": uuid4()})
    elif case == "past":
        body = body.model_copy(update={"starts_at": NOW})
    elif case == "unknown_user":
        user = uuid4()
    elif case == "user":
        with Session(db_engine) as session, session.begin():
            record = session.get(ApplicationUser, user)
            assert record is not None
            record.is_active = False
    else:
        with Session(db_engine) as session, locked_room(session, body.room_id) as room:
            if case == "inactive":
                room.room.active = False
            else:
                room.room.hours_confirmed = False
    with pytest.raises(ApiError) as caught:
        create(db_engine, user, key, body)
    assert caught.value.code == code
    assert counts(db_engine) == (0, 0, 0)


def test_atomic_failure_after_booking_insert_allows_same_key_retry(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate]
) -> None:
    user, _, body = owned_room
    key = uuid4()

    def fail(_mapper: object, _connection: object, _target: object) -> None:
        raise RuntimeError("Synthetic result write failure")

    event.listen(BookingRequest, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="Synthetic"):
            create(db_engine, user, key, body)
    finally:
        event.remove(BookingRequest, "before_insert", fail)
    assert counts(db_engine) == (0, 0, 0)
    assert create(db_engine, user, key, body).owner_id == user
    assert counts(db_engine) == (1, 1, 1)


def test_same_key_concurrent_inflight_then_replay(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate]
) -> None:
    user, _, body = owned_room
    key = uuid4()
    inserted, release = Event(), Event()

    def hold(_mapper: object, _connection: object, _target: object) -> None:
        inserted.set()
        assert release.wait(5)

    event.listen(Booking, "after_insert", hold)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(create, db_engine, user, key, body)
            try:
                assert inserted.wait(5)
                with pytest.raises(ApiError) as caught:
                    create(db_engine, user, key, body)
                assert caught.value.code == "REQUEST_IN_PROGRESS"
                # A changed room still uses the same per-user key lock.
                with pytest.raises(ApiError) as changed:
                    create(db_engine, user, key, body.model_copy(update={"room_id": uuid4()}))
                assert changed.value.code == "REQUEST_IN_PROGRESS"
            finally:
                release.set()
            original = future.result(5)
    finally:
        event.remove(Booking, "after_insert", hold)
    assert create(db_engine, user, key, body) == original
    assert counts(db_engine) == (1, 1, 1)


def test_different_keys_race_for_same_slot_only_one_commits(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate]
) -> None:
    user, other, body = owned_room

    def attempt(owner: UUID) -> str:
        try:
            create(db_engine, owner, uuid4(), body)
            return "created"
        except ApiError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, [user, other]))
    assert sorted(results) == ["ROOM_UNAVAILABLE", "created"]
    assert counts(db_engine) == (1, 1, 1)


@pytest.mark.parametrize("booking_first", [True, False])
def test_actual_booking_service_and_closure_race(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate], booking_first: bool
) -> None:
    user, _, body = owned_room
    locked, release, contender = Event(), Event(), Event()

    def hold(_mapper: object, _connection: object, _target: object) -> None:
        locked.set()
        assert release.wait(5)

    def booking() -> str:
        contender.set()
        try:
            create(db_engine, user, uuid4(), body)
            return "created"
        except ApiError as error:
            return error.code

    def closure() -> str:
        contender.set()
        try:
            with (
                Session(db_engine) as session,
                locked_room(session, body.room_id, clock=lambda: NOW),
            ):
                session.add(
                    Closure(room_id=body.room_id, starts_at=START, ends_at=END, reason="Test")
                )
                session.flush()
            return "closed"
        except ApiError as error:
            return error.code

    model = Booking if booking_first else Closure
    event.listen(model, "after_insert", hold)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(booking if booking_first else closure)
            try:
                assert locked.wait(5)
                contender.clear()
                second = executor.submit(closure if booking_first else booking)
                assert contender.wait(5)
            finally:
                release.set()
            assert first.result(5) == ("created" if booking_first else "closed")
            assert second.result(5) == (
                "BOOKINGS_AFFECTED" if booking_first else "ROOM_UNAVAILABLE"
            )
    finally:
        event.remove(model, "after_insert", hold)
    assert counts(db_engine) == ((1, 1, 1) if booking_first else (0, 0, 0))


def test_room_lock_timeout_is_retryable_and_rolls_back_key(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate]
) -> None:
    user, _, body = owned_room
    key = uuid4()
    with Session(db_engine) as blocker, locked_room(blocker, body.room_id):
        with db_engine.connect() as connection:
            connection.execute(text("SET lock_timeout='50ms'"))
            connection.commit()
            with Session(connection) as session, pytest.raises(ApiError) as caught:
                create_booking(session, user_id=user, key=key, body=body, clock=lambda: NOW)
            assert caught.value.code == "BOOKING_BUSY"
    assert counts(db_engine) == (0, 0, 0)
    assert create(db_engine, user, key, body).owner_id == user


def test_clean_session_guards(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate]
) -> None:
    user, _, body = owned_room
    with Session(db_engine) as session:
        with (
            pytest.raises(RuntimeError, match="active service-owned"),
            room_in_transaction(session, body.room_id),
        ):
            pass
        with session.begin(), pytest.raises(RuntimeError, match="clean session"):
            create_booking(session, user_id=user, key=uuid4(), body=body)
    assert request_lock_id(user, uuid4()) != request_lock_id(uuid4(), uuid4())


def test_named_exclusion_is_final_defence_when_precheck_misses_a_booking(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.availability.policy import Interval
    from app.modules.availability.service import LockedRoom

    user, other, body = owned_room
    create(db_engine, user, uuid4(), body)
    # Simulate a stale/bypassed precheck; PostgreSQL must still deny the insert.
    monkeypatch.setattr(LockedRoom, "require_available", lambda *args: Interval(START, END))
    with pytest.raises(ApiError) as caught:
        create(db_engine, other, uuid4(), body)
    assert caught.value.code == "ROOM_UNAVAILABLE"
    assert counts(db_engine) == (1, 1, 1)


def test_unrelated_constraint_error_is_not_misreported_as_availability(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate]
) -> None:
    from sqlalchemy.exc import IntegrityError

    user, _, body = owned_room

    def invalid_result(_mapper: object, _connection: object, target: BookingRequest) -> None:
        target.booking_id = uuid4()

    event.listen(BookingRequest, "before_insert", invalid_result)
    try:
        with pytest.raises(IntegrityError):
            create(db_engine, user, uuid4(), body)
    finally:
        event.remove(BookingRequest, "before_insert", invalid_result)
    assert counts(db_engine) == (0, 0, 0)


def test_non_read_committed_session_rejected(
    db_engine: Engine, owned_room: tuple[UUID, UUID, BookingCreate]
) -> None:
    user, _, body = owned_room
    with db_engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with Session(connection) as session, pytest.raises(RuntimeError, match="READ COMMITTED"):
            create_booking(session, user_id=user, key=uuid4(), body=body)
