import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import DateTime, Engine, Text, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.modules.bookings.models import Booking
from app.modules.identity.models import ApplicationUser, AuditEvent, AuthSession, ExternalIdentity
from app.modules.rooms.models import Room
from scripts.inventory_legacy_bookings import inventory_legacy_bookings

pytestmark = pytest.mark.database
NOW = datetime(2026, 10, 19, 2, tzinfo=UTC)
ISSUER = "https://identity.example.test/auth/v1"


def add_identity(session: Session) -> tuple[ApplicationUser, ExternalIdentity]:
    user = ApplicationUser()
    session.add(user)
    session.flush()
    identity = ExternalIdentity(user_id=user.id, issuer=ISSUER, subject=str(uuid4()))
    session.add(identity)
    session.flush()
    return user, identity


def auth_session(
    user: ApplicationUser, identity: ExternalIdentity, **changes: object
) -> AuthSession:
    values: dict[str, object] = {
        "user_id": user.id,
        "external_identity_id": identity.id,
        "token_hash": uuid4().hex + uuid4().hex,
        "access_token_ciphertext": "encrypted-access",
        "refresh_token_ciphertext": "encrypted-refresh",
        "provider_session_id": str(uuid4()),
        "created_at": NOW,
        "last_seen_at": NOW,
        "last_provider_check_at": NOW,
        "absolute_expires_at": NOW + timedelta(hours=12),
        "access_expires_at": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return AuthSession(**values)


def test_identity_defaults_and_aware_timestamp_storage(db_session: Session) -> None:
    user, identity = add_identity(db_session)
    item = auth_session(user, identity, access_token_ciphertext="encrypted-" + "x" * 10000)
    event = AuditEvent(actor_user_id=user.id, target_id=item.id, action="session.created")
    db_session.add_all([item, event])
    db_session.flush()
    db_session.refresh(item)
    db_session.refresh(event)
    assert user.role == "Member"
    assert user.is_active is True
    assert item.aal == "aal1"
    assert item.purpose == "standard"
    assert item.revoked_at is None
    assert item.refresh_owner is None
    assert item.refresh_until is None
    assert item.created_at.utcoffset() == timedelta(0)
    assert item.access_expires_at.utcoffset() == timedelta(0)
    assert event.details == {}
    assert event.occurred_at.tzinfo is not None


def test_external_identity_unique_by_issuer_and_subject_not_email(db_session: Session) -> None:
    user, identity = add_identity(db_session)
    second_user = ApplicationUser()
    db_session.add(second_user)
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            ExternalIdentity(user_id=second_user.id, issuer=ISSUER, subject=identity.subject)
        )
        db_session.flush()
    # The same subject at a different issuer is a different identity.
    db_session.add(
        ExternalIdentity(
            user_id=second_user.id,
            issuer="https://another.example.test/auth/v1",
            subject=identity.subject,
        )
    )
    db_session.flush()
    assert "email" not in ExternalIdentity.__table__.c
    assert user.id != second_user.id


def test_session_cannot_reference_another_users_identity(db_session: Session) -> None:
    user, identity = add_identity(db_session)
    other = ApplicationUser()
    db_session.add(other)
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(auth_session(other, identity))
        db_session.flush()
    assert user.id != other.id


def test_duplicate_session_hash_is_rejected(db_session: Session) -> None:
    user, identity = add_identity(db_session)
    first = auth_session(user, identity)
    db_session.add(first)
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(auth_session(user, identity, token_hash=first.token_hash))
        db_session.flush()


@pytest.mark.parametrize(
    "changes",
    [
        {"token_hash": "plaintext-session-token"},
        {"token_hash": "X" * 64},
        {"aal": "aal3"},
        {"purpose": "admin"},
        {"absolute_expires_at": NOW},
        {"provider_session_id": "not-a-provider-session"},
        {"refresh_owner": uuid4(), "refresh_until": None},
        {"refresh_owner": None, "refresh_until": NOW + timedelta(seconds=15)},
    ],
)
def test_session_invalid_state_is_database_rejected(
    db_session: Session, changes: dict[str, object]
) -> None:
    user, identity = add_identity(db_session)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(auth_session(user, identity, **changes))
        db_session.flush()


def test_user_role_and_foreign_keys_are_database_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(ApplicationUser(role="Owner"))
        db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(ExternalIdentity(user_id=uuid4(), issuer=ISSUER, subject=str(uuid4())))
        db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(AuditEvent(actor_user_id=uuid4(), action="session.created"))
        db_session.flush()


def test_audit_details_must_be_an_object(db_session: Session) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            text(
                "INSERT INTO audit_events (id, action, details) VALUES (:id, 'test', '[]'::jsonb)"
            ),
            {"id": uuid4()},
        )


def test_legacy_inventory_returns_only_counts_and_does_not_mutate(db_session: Session) -> None:
    room = Room(name="Inventory room", location="Test building", capacity=4)
    db_session.add(room)
    db_session.flush()
    first = Booking(room_id=room.id, starts_at=NOW, ends_at=NOW + timedelta(hours=1))
    second = Booking(
        room_id=room.id,
        starts_at=NOW,
        ends_at=NOW + timedelta(hours=1),
        status="cancelled",
        cancelled_at=NOW,
    )
    db_session.add_all([first, second])
    db_session.flush()
    report = inventory_legacy_bookings(db_session)
    assert report == {
        "ownership": "not_assigned",
        "total": 2,
        "by_status": {"active": 1, "cancelled": 1},
    }
    rendered = json.dumps(report)
    assert str(first.id) not in rendered
    assert room.name not in rendered
    assert db_session.scalars(select(Booking)).all() == [first, second]


def test_prior_schema_upgrade_preserves_rooms_and_bookings_and_refuses_data_loss(
    database_url: str, db_engine: Engine, clean_database: None
) -> None:
    config = Config("alembic.ini")
    room_id, booking_id, user_id = uuid4(), uuid4(), uuid4()
    with patch.dict(os.environ, {"ROOMBOOK_DATABASE_URL": database_url}):
        command.downgrade(config, "0001")
        with db_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO rooms (id, name, location, capacity) "
                    "VALUES (:id, 'Retained', 'Test', 4)"
                ),
                {"id": room_id},
            )
            connection.execute(
                text(
                    "INSERT INTO bookings (id, room_id, starts_at, ends_at) "
                    "VALUES (:id, :room, :start, :end)"
                ),
                {"id": booking_id, "room": room_id, "start": NOW, "end": NOW + timedelta(hours=1)},
            )
            before = connection.execute(
                text("SELECT * FROM bookings WHERE id = :id"), {"id": booking_id}
            ).one()
        try:
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            with db_engine.begin() as connection:
                after = connection.execute(
                    text("SELECT * FROM bookings WHERE id = :id"), {"id": booking_id}
                ).one()
                assert tuple(after) == tuple(before)
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM rooms WHERE id = :id"), {"id": room_id}
                    )
                    == 1
                )
                connection.execute(
                    text("INSERT INTO application_users (id) VALUES (:id)"), {"id": user_id}
                )
            with pytest.raises(DBAPIError, match="Identity tables contain data"):
                command.downgrade(config, "0001")
            with db_engine.begin() as connection:
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM application_users WHERE id = :id"),
                        {"id": user_id},
                    )
                    == 1
                )
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002"
                connection.execute(
                    text("DELETE FROM application_users WHERE id = :id"), {"id": user_id}
                )
        finally:
            command.upgrade(config, "head")
    schema = inspect(db_engine)
    assert "user_id" not in {column["name"] for column in schema.get_columns("bookings")}
    for table in ("application_users", "external_identities", "auth_sessions", "audit_events"):
        for column in schema.get_columns(table):
            column_type = column["type"]
            if isinstance(column_type, DateTime):
                assert column_type.timezone is True
    session_columns = {column["name"]: column for column in schema.get_columns("auth_sessions")}
    assert isinstance(session_columns["access_token_ciphertext"]["type"], Text)
    assert isinstance(session_columns["refresh_token_ciphertext"]["type"], Text)
