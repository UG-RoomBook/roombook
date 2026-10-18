"""Session behavior against real PostgreSQL; providers are deterministic local doubles."""

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.session import Database
from app.modules.identity.crypto import TokenCipher
from app.modules.identity.models import ApplicationUser, AuditEvent, AuthSession, ExternalIdentity
from app.modules.identity.service import (
    InvalidSession,
    SessionPolicy,
    SessionService,
    hash_token,
)
from app.modules.identity.types import (
    InvalidIdentity,
    ProviderTokens,
    ProviderUnavailable,
    VerifiedIdentity,
)

pytestmark = pytest.mark.database
START = datetime(2026, 10, 19, 3, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class TrackingDatabase(Database):
    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.local = threading.local()

    @contextmanager
    def session(self) -> Iterator[Session]:
        assert not getattr(self.local, "inside_session", False)
        self.local.inside_session = True
        try:
            with super().session() as session:
                yield session
        finally:
            self.local.inside_session = False


class Provider:
    def __init__(self, database: TrackingDatabase) -> None:
        self.database = database
        self.identity = VerifiedIdentity(
            issuer="https://test-identity.invalid/auth/v1",
            subject=str(uuid4()),
            session_id=str(uuid4()),
            email="member@example.invalid",
            email_verified=True,
            aal="aal1",
            expires_at=START + timedelta(hours=1),
        )
        self.verify_calls = 0
        self.refresh_calls = 0
        self.revalidate_calls = 0
        self.verify_hook: Callable[[], None] = lambda: None
        self.refresh_hook: Callable[[], None] = lambda: None
        self.revalidate_hook: Callable[[], None] = lambda: None
        self.revalidate_error: Exception | None = None
        self.refresh_error: Exception | None = None
        self.refreshed_identity: VerifiedIdentity | None = None
        self.revalidated_identity: VerifiedIdentity | None = None

    def _outside_transaction(self) -> None:
        assert not getattr(self.database.local, "inside_session", False)

    def verify(self, access_token: str) -> VerifiedIdentity:
        self._outside_transaction()
        self.verify_calls += 1
        self.verify_hook()
        value = self.refreshed_identity if access_token == "new-access-secret" else self.identity
        assert value is not None
        # Standard Supabase JWTs have no authoritative email-confirmation claim.
        return replace(value, email_verified=False)

    def revalidate(self, access_token: str) -> VerifiedIdentity:
        self._outside_transaction()
        self.revalidate_calls += 1
        self.revalidate_hook()
        if self.revalidate_error is not None:
            raise self.revalidate_error
        if self.revalidated_identity is not None:
            return self.revalidated_identity
        value = self.refreshed_identity if access_token == "new-access-secret" else self.identity
        assert value is not None
        return value

    def refresh(self, refresh_token: str) -> ProviderTokens:
        self._outside_transaction()
        assert refresh_token == "refresh-secret"
        self.refresh_calls += 1
        self.refresh_hook()
        if self.refresh_error is not None:
            raise self.refresh_error
        if self.refreshed_identity is None:
            self.refreshed_identity = replace(
                self.identity, expires_at=self.identity.expires_at + timedelta(hours=1)
            )
        return ProviderTokens("new-access-secret", "new-refresh-secret")


class Harness:
    def __init__(self, database: TrackingDatabase, engine: Engine) -> None:
        self.database = database
        self.engine = engine
        self.clock = Clock()
        self.provider = Provider(database)
        self.cipher = TokenCipher(Fernet.generate_key().decode("ascii"))
        self.service = SessionService(database, self.provider, self.cipher, clock=self.clock)

    def establish(self, **kwargs: object) -> str:
        result = self.service.establish(
            ProviderTokens("access-secret", "refresh-secret"),
            **kwargs,  # type: ignore[arg-type]
        )
        return result.opaque_token

    def record(self, token: str) -> AuthSession:
        with Session(self.engine) as db:
            record = db.scalar(
                select(AuthSession).where(AuthSession.token_hash == hash_token(token))
            )
            assert record is not None
            db.expunge(record)
            return record

    def update_record(self, token: str, **values: object) -> None:
        with Session(self.engine) as db, db.begin():
            record = db.scalar(
                select(AuthSession).where(AuthSession.token_hash == hash_token(token))
            )
            assert record is not None
            for key, value in values.items():
                setattr(record, key, value)

    def update_user(self, user_id: UUID, **values: object) -> None:
        with Session(self.engine) as db, db.begin():
            user = db.get(ApplicationUser, user_id)
            assert user is not None
            for key, value in values.items():
                setattr(user, key, value)


@pytest.fixture
def harness(database_url: str, db_engine: Engine, clean_database: None) -> Iterator[Harness]:
    database = TrackingDatabase(database_url)
    try:
        yield Harness(database, db_engine)
    finally:
        database.dispose()


def test_establish_stores_hashes_and_ciphertext_and_safe_audit(harness: Harness) -> None:
    token = harness.establish()
    assert len(token) == 43
    record = harness.record(token)
    assert record.token_hash == hash_token(token)
    assert record.token_hash != token
    assert record.access_token_ciphertext != "access-secret"
    assert record.refresh_token_ciphertext != "refresh-secret"
    assert harness.cipher.decrypt(record.access_token_ciphertext) == "access-secret"
    result = harness.service.authenticate(token)
    assert result.role == "Member"
    assert result.purpose == "standard"
    assert result.aal == "aal1"
    assert result.expires_at == START + timedelta(minutes=30)
    assert result.csrf_token == harness.cipher.csrf_token(token)
    assert token not in repr(result)
    assert result.csrf_token not in repr(result)
    with Session(harness.engine) as db:
        events = db.scalars(select(AuditEvent)).all()
        assert [event.action for event in events] == ["session.established"]
        assert events[0].details == {"purpose": "standard"}
        assert "secret" not in repr(events[0].details)
        assert "email" not in repr(events[0].details)


def test_identity_link_is_issuer_subject_and_not_email(harness: Harness) -> None:
    first = harness.record(harness.establish())
    harness.provider.identity = replace(harness.provider.identity, email="changed@example.invalid")
    second = harness.record(harness.establish())
    assert first.user_id == second.user_id
    harness.provider.identity = replace(harness.provider.identity, subject=str(uuid4()))
    third = harness.record(harness.establish())
    assert third.user_id != second.user_id
    with Session(harness.engine) as db:
        assert db.scalar(select(func.count()).select_from(ApplicationUser)) == 2


def test_concurrent_establish_creates_one_identity_without_orphan_user(harness: Harness) -> None:
    barrier = threading.Barrier(2)

    def await_both() -> None:
        barrier.wait(timeout=3)

    harness.provider.revalidate_hook = await_both
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: harness.establish(), range(2)))
    assert len(set(results)) == 2
    with Session(harness.engine) as db:
        assert db.scalar(select(func.count()).select_from(ApplicationUser)) == 1
        assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 2


def test_reauthentication_rotates_local_token_and_revokes_previous(harness: Harness) -> None:
    old = harness.establish()
    new = harness.establish(previous_token=old)
    assert old != new
    with pytest.raises(InvalidSession):
        harness.service.authenticate(old)
    assert harness.service.authenticate(new).user_id == harness.record(old).user_id
    assert harness.record(old).revoked_at == START


def test_recovery_purpose_is_preserved_for_http_restrictions(harness: Harness) -> None:
    result = harness.service.authenticate(harness.establish(purpose="recovery"))
    assert result.purpose == "recovery"
    with pytest.raises(InvalidSession):
        harness.establish(purpose="administrator")


def test_unverified_identity_cannot_establish_session(harness: Harness) -> None:
    harness.provider.identity = replace(harness.provider.identity, email_verified=False)
    with pytest.raises(InvalidIdentity):
        harness.establish()
    with Session(harness.engine) as db:
        assert db.scalar(select(func.count()).select_from(ApplicationUser)) == 0


def test_current_database_role_and_active_state_are_used(harness: Harness) -> None:
    token = harness.establish()
    user_id = harness.record(token).user_id
    harness.update_user(user_id, role="Admin")
    assert harness.service.authenticate(token).role == "Admin"
    harness.update_user(user_id, is_active=False)
    with pytest.raises(ApiError) as error:
        harness.service.authenticate(token)
    assert error.value.code == "ACCOUNT_INACTIVE"
    assert harness.record(token).revoked_at is not None
    with pytest.raises(ApiError):
        harness.establish()


def test_idle_expiry_denies_and_revokes(harness: Harness) -> None:
    token = harness.establish()
    harness.clock.advance(1800)
    with pytest.raises(InvalidSession):
        harness.service.authenticate(token)
    assert harness.record(token).revoked_at == harness.clock()


def test_absolute_expiry_is_not_extended_by_last_seen(harness: Harness) -> None:
    token = harness.establish()
    harness.clock.advance(43200)
    harness.update_record(token, last_seen_at=harness.clock())
    with pytest.raises(InvalidSession):
        harness.service.authenticate(token)
    assert harness.record(token).absolute_expires_at == START + timedelta(hours=12)


def test_provider_validation_is_per_request_but_user_check_is_bounded(harness: Harness) -> None:
    token = harness.establish()
    harness.service.authenticate(token)
    harness.clock.advance(299)
    harness.service.authenticate(token)
    assert harness.provider.verify_calls == 3
    assert harness.provider.revalidate_calls == 1
    harness.clock.advance(1)
    harness.service.authenticate(token)
    assert harness.provider.revalidate_calls == 2
    assert harness.record(token).last_provider_check_at == harness.clock()


def test_due_provider_outage_never_extends_stale_validation(harness: Harness) -> None:
    token = harness.establish()
    harness.clock.advance(300)
    harness.provider.revalidate_error = ProviderUnavailable()
    for _ in range(2):
        with pytest.raises(ProviderUnavailable):
            harness.service.authenticate(token)
    record = harness.record(token)
    assert record.last_provider_check_at == START
    assert record.last_seen_at == START
    assert record.refresh_owner is None
    assert record.revoked_at is None
    harness.provider.revalidate_error = None
    assert harness.service.authenticate(token).opaque_token == token


def test_provider_revocation_denies_and_revokes_local_session(harness: Harness) -> None:
    token = harness.establish()
    harness.clock.advance(300)
    harness.provider.revalidate_error = InvalidIdentity()
    with pytest.raises(InvalidSession):
        harness.service.authenticate(token)
    assert harness.record(token).revoked_at == harness.clock()


def test_corrupt_stored_token_fails_closed(harness: Harness) -> None:
    token = harness.establish()
    harness.update_record(token, access_token_ciphertext="not-a-ciphertext")
    with pytest.raises(InvalidSession) as error:
        harness.service.authenticate(token)
    assert "ciphertext" not in str(error.value)
    assert harness.record(token).revoked_at is not None


def _prepare_refresh(harness: Harness, token: str) -> None:
    harness.provider.identity = replace(
        harness.provider.identity, expires_at=START + timedelta(seconds=59)
    )
    harness.update_record(token, access_expires_at=harness.provider.identity.expires_at)


def test_refresh_preserves_local_token_and_provider_session(harness: Harness) -> None:
    token = harness.establish()
    _prepare_refresh(harness, token)
    result = harness.service.authenticate(token)
    record = harness.record(token)
    assert result.opaque_token == token
    assert record.provider_session_id == harness.provider.identity.session_id
    assert record.aal == "aal1"
    assert harness.cipher.decrypt(record.access_token_ciphertext) == "new-access-secret"
    assert harness.cipher.decrypt(record.refresh_token_ciphertext) == "new-refresh-secret"
    assert record.refresh_owner is None
    assert record.refresh_until is None
    assert harness.provider.refresh_calls == 1
    assert harness.service.authenticate(token).opaque_token == token


@pytest.mark.parametrize("change", [{"session_id": str(uuid4())}, {"aal": "aal2"}])
def test_refresh_cannot_change_provider_session_or_assurance(
    harness: Harness, change: dict[str, str]
) -> None:
    token = harness.establish()
    _prepare_refresh(harness, token)
    harness.provider.refreshed_identity = replace(
        harness.provider.identity,
        expires_at=START + timedelta(hours=1),
        session_id=change.get("session_id", harness.provider.identity.session_id),
        aal=change.get("aal", harness.provider.identity.aal),
    )
    with pytest.raises(InvalidSession):
        harness.service.authenticate(token)
    assert harness.record(token).revoked_at is not None


def test_ambiguous_refresh_outage_revokes_instead_of_reusing_token(harness: Harness) -> None:
    token = harness.establish()
    _prepare_refresh(harness, token)
    harness.provider.refresh_error = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        harness.service.authenticate(token)
    with pytest.raises(InvalidSession):
        harness.service.authenticate(token)
    assert harness.provider.refresh_calls == 1
    assert harness.record(token).revoked_at is not None


def test_cross_process_style_services_refresh_once_and_follow_new_tokens(harness: Harness) -> None:
    token = harness.establish()
    _prepare_refresh(harness, token)
    started, release = threading.Event(), threading.Event()

    def blocked_refresh() -> None:
        started.set()
        assert release.wait(timeout=3)

    harness.provider.refresh_hook = blocked_refresh
    follower = SessionService(
        harness.database, harness.provider, harness.cipher, clock=harness.clock
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(harness.service.authenticate, token)
        assert started.wait(timeout=3)
        second = executor.submit(follower.authenticate, token)
        time.sleep(0.06)
        release.set()
        assert first.result(timeout=3).opaque_token == token
        assert second.result(timeout=3).opaque_token == token
    assert harness.provider.refresh_calls == 1


def test_busy_refresh_wait_is_bounded_without_using_old_credentials(harness: Harness) -> None:
    token = harness.establish()
    harness.update_record(token, refresh_owner=uuid4(), refresh_until=START + timedelta(seconds=15))
    service = SessionService(
        harness.database,
        harness.provider,
        harness.cipher,
        SessionPolicy(refresh_wait_seconds=0.05),
        clock=harness.clock,
    )
    start = time.monotonic()
    with pytest.raises(ProviderUnavailable):
        service.authenticate(token)
    assert time.monotonic() - start < 0.5
    assert harness.provider.refresh_calls == 0
    assert harness.provider.verify_calls == 1


def test_expired_refresh_lease_is_not_stolen(harness: Harness) -> None:
    token = harness.establish()
    harness.update_record(token, refresh_owner=uuid4(), refresh_until=START - timedelta(seconds=1))
    with pytest.raises(InvalidSession):
        harness.service.authenticate(token)
    assert harness.provider.refresh_calls == 0
    assert harness.record(token).revoked_at is not None


def test_logout_wins_refresh_race_and_old_credentials_are_not_restored(harness: Harness) -> None:
    token = harness.establish()
    _prepare_refresh(harness, token)
    started, release = threading.Event(), threading.Event()

    def blocked_refresh() -> None:
        started.set()
        assert release.wait(timeout=3)

    harness.provider.refresh_hook = blocked_refresh
    with ThreadPoolExecutor(max_workers=1) as executor:
        request = executor.submit(harness.service.authenticate, token)
        assert started.wait(timeout=3)
        harness.service.logout(token)
        release.set()
        with pytest.raises(InvalidSession):
            request.result(timeout=3)
    record = harness.record(token)
    assert record.revoked_at is not None
    assert harness.cipher.decrypt(record.access_token_ciphertext) == "access-secret"


@pytest.mark.parametrize("change", [{"is_active": False}, {"role": "Admin"}])
def test_provider_revalidation_rechecks_local_access_before_completion(
    harness: Harness, change: dict[str, bool | str]
) -> None:
    token = harness.establish()
    harness.clock.advance(300)
    harness.provider.revalidate_hook = lambda: harness.update_user(
        harness.record(token).user_id, **change
    )
    if change.get("is_active") is False:
        with pytest.raises(ApiError) as error:
            harness.service.authenticate(token)
        assert error.value.code == "ACCOUNT_INACTIVE"
    else:
        assert harness.service.authenticate(token).role == "Admin"


def test_provider_lease_expiry_during_network_call_fails_closed(harness: Harness) -> None:
    token = harness.establish()
    _prepare_refresh(harness, token)
    harness.provider.refresh_hook = lambda: harness.clock.advance(16)
    with pytest.raises(InvalidSession):
        harness.service.authenticate(token)
    assert harness.record(token).revoked_at is not None


def test_logout_is_idempotent_local_and_safe_during_provider_outage(harness: Harness) -> None:
    token = harness.establish()
    harness.provider.revalidate_error = ProviderUnavailable()
    harness.provider.refresh_error = ProviderUnavailable()
    harness.service.logout(token)
    harness.service.logout(token)
    harness.service.logout("not-a-valid-token")
    with pytest.raises(InvalidSession):
        harness.service.authenticate(token)
    assert harness.provider.revalidate_calls == 1
    with Session(harness.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "session.revoked")
            )
            == 1
        )


def test_revoke_user_sessions_is_scoped_and_idempotent(harness: Harness) -> None:
    first, second = harness.establish(), harness.establish()
    user_id = harness.record(first).user_id
    harness.provider.identity = replace(harness.provider.identity, subject=str(uuid4()))
    other = harness.establish()
    assert harness.service.revoke_user_sessions(user_id) == 2
    assert harness.service.revoke_user_sessions(user_id) == 0
    assert harness.service.revoke_user_sessions(uuid4()) == 0
    for token in (first, second):
        with pytest.raises(InvalidSession):
            harness.service.authenticate(token)
    assert harness.service.authenticate(other).opaque_token == other


@pytest.mark.parametrize("operation", ["logout", "expired"])
def test_local_revocation_locks_user_before_session_to_avoid_audit_deadlock(
    harness: Harness, operation: str
) -> None:
    token = harness.establish()
    record = harness.record(token)
    if operation == "expired":
        harness.clock.advance(1800)
    reached_user_lock = threading.Event()
    assert harness.database.engine is not None

    def before_sql(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if "application_users" in statement and "FOR UPDATE" in statement:
            reached_user_lock.set()

    event.listen(harness.database.engine, "before_cursor_execute", before_sql)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with Session(harness.engine) as db, db.begin():
                db.scalar(
                    select(ApplicationUser)
                    .where(ApplicationUser.id == record.user_id)
                    .with_for_update()
                )
                action = (
                    harness.service.logout
                    if operation == "logout"
                    else harness.service.authenticate
                )
                request = executor.submit(action, token)
                assert reached_user_lock.wait(timeout=0.5)
                # The waiting revoker must not already own the session row while awaiting user.
                assert (
                    db.scalar(
                        select(AuthSession)
                        .where(AuthSession.id == record.id)
                        .with_for_update(nowait=True)
                    )
                    is not None
                )
            if operation == "expired":
                with pytest.raises(InvalidSession):
                    request.result(timeout=3)
            else:
                assert request.result(timeout=3) is None
    finally:
        event.remove(harness.database.engine, "before_cursor_execute", before_sql)


def test_provider_expiry_during_database_lock_wait_is_rejected(harness: Harness) -> None:
    token = harness.establish()
    _prepare_refresh(harness, token)
    harness.provider.refreshed_identity = replace(
        harness.provider.identity, expires_at=START + timedelta(seconds=3)
    )
    user_lock_calls = 0
    assert harness.database.engine is not None

    def before_sql(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        nonlocal user_lock_calls
        if "application_users" in statement and "FOR UPDATE" in statement:
            user_lock_calls += 1
            if user_lock_calls == 2:
                harness.clock.advance(4)

    event.listen(harness.database.engine, "before_cursor_execute", before_sql)
    try:
        with pytest.raises(InvalidSession):
            harness.service.authenticate(token)
    finally:
        event.remove(harness.database.engine, "before_cursor_execute", before_sql)
    assert harness.record(token).revoked_at is not None
