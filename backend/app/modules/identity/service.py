"""Local opaque sessions with bounded provider checks and cross-process refresh leases."""

import hashlib
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.session import Database
from app.modules.identity.crypto import TokenCipher
from app.modules.identity.models import ApplicationUser, AuditEvent, AuthSession, ExternalIdentity
from app.modules.identity.types import (
    IdentityProvider,
    InvalidIdentity,
    ProviderTokens,
    ProviderUnavailable,
    VerifiedIdentity,
)

_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class InvalidSession(Exception):
    def __init__(self) -> None:
        super().__init__("The session is invalid or has expired.")


def hash_token(value: str) -> str:
    """Only fixed-length, server-generated token shapes reach database lookups."""
    if not _OPAQUE_TOKEN.fullmatch(value):
        raise InvalidSession()
    return hashlib.sha256(value.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class SessionPolicy:
    idle_seconds: int = 1800
    absolute_seconds: int = 43200
    revalidate_seconds: int = 300
    refresh_margin_seconds: int = 60
    refresh_lease_seconds: int = 15
    refresh_wait_seconds: float = 2.0

    def __post_init__(self) -> None:
        if (
            self.idle_seconds <= 0
            or self.absolute_seconds < self.idle_seconds
            or not 0 < self.revalidate_seconds <= 300
            or self.refresh_margin_seconds < 0
            or self.refresh_lease_seconds <= 0
            or not 0 <= self.refresh_wait_seconds <= 2
        ):
            raise ValueError("Authentication session policy is invalid.")


@dataclass(frozen=True)
class SessionResult:
    user_id: UUID
    role: str
    aal: str
    purpose: str
    expires_at: datetime
    csrf_token: str = field(repr=False)
    opaque_token: str = field(repr=False)
    mfa_verified_at: datetime | None = None


_DEFAULT_POLICY = SessionPolicy()


@dataclass(frozen=True)
class _Snapshot:
    id: UUID
    user_id: UUID
    external_identity_id: UUID
    role: str
    is_active: bool
    issuer: str
    subject: str
    token_hash: str = field(repr=False)
    access_token_ciphertext: str = field(repr=False)
    refresh_token_ciphertext: str = field(repr=False)
    provider_session_id: str
    aal: str
    purpose: str
    last_seen_at: datetime
    absolute_expires_at: datetime
    access_expires_at: datetime
    last_provider_check_at: datetime
    revoked_at: datetime | None
    refresh_owner: UUID | None
    refresh_until: datetime | None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SessionService:
    def __init__(
        self,
        database: Database,
        provider: IdentityProvider,
        cipher: TokenCipher,
        policy: SessionPolicy = _DEFAULT_POLICY,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.database = database
        self.provider = provider
        self.cipher = cipher
        self.policy = policy
        self.clock = clock

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Authentication clock must be timezone-aware.")
        return value.astimezone(UTC)

    @staticmethod
    def _audit(
        db: Session,
        user_id: UUID,
        target_id: UUID,
        action: str,
        now: datetime,
        *,
        reason: str | None = None,
        purpose: str | None = None,
        count: int | None = None,
    ) -> None:
        # Only internal fields are admitted; provider claims and caller text never enter audit.
        details: dict[str, str | int] = {}
        if reason is not None:
            details["reason"] = reason
        if purpose is not None:
            details["purpose"] = purpose
        if count is not None:
            details["count"] = count
        db.add(
            AuditEvent(
                actor_user_id=user_id,
                target_id=target_id,
                action=action,
                occurred_at=now,
                details=details,
            )
        )

    def establish(
        self,
        tokens: ProviderTokens,
        *,
        previous_token: str | None = None,
        purpose: str = "standard",
        mfa_user: UUID | None = None,
    ) -> SessionResult:
        """Internal entry point after credentials/OTP; never accepts browser provider tokens."""
        if purpose not in {"standard", "recovery"}:
            raise InvalidSession()
        verified = self.provider.verify(tokens.access_token)
        identity = self.provider.revalidate(tokens.access_token)
        self._check_identity(verified, identity)
        now = self._now()
        if not identity.email_verified or identity.expires_at <= now:
            raise InvalidIdentity()
        if mfa_user is not None and (
            identity.aal != "aal2"
            or identity.mfa_verified_at is None
            or not now - timedelta(minutes=10) <= identity.mfa_verified_at <= now
        ):
            raise InvalidIdentity()
        opaque_token = secrets.token_urlsafe(32)
        token_hash = hash_token(opaque_token)
        access_ciphertext = self.cipher.encrypt(tokens.access_token)
        refresh_ciphertext = self.cipher.encrypt(tokens.refresh_token)
        previous_hash: str | None = None
        if previous_token is not None and _OPAQUE_TOKEN.fullmatch(previous_token):
            previous_hash = hash_token(previous_token)

        with self.database.session() as db, db.begin():
            external = db.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.issuer == identity.issuer,
                    ExternalIdentity.subject == identity.subject,
                )
            )
            if external is None:
                user_id = uuid4()
                db.add(ApplicationUser(id=user_id, role="Member", is_active=True, created_at=now))
                db.flush()
                identity_id = db.scalar(
                    insert(ExternalIdentity)
                    .values(
                        id=uuid4(),
                        user_id=user_id,
                        issuer=identity.issuer,
                        subject=identity.subject,
                        created_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["issuer", "subject"])
                    .returning(ExternalIdentity.id)
                )
                if identity_id is None:
                    # A simultaneous establishment won the identity. Do not leave an orphan user.
                    tentative_user = db.get(ApplicationUser, user_id)
                    assert tentative_user is not None
                    db.delete(tentative_user)
                    db.flush()
                external = db.scalar(
                    select(ExternalIdentity).where(
                        ExternalIdentity.issuer == identity.issuer,
                        ExternalIdentity.subject == identity.subject,
                    )
                )
                assert external is not None
            previous_user_id = (
                db.scalar(
                    select(AuthSession.user_id).where(AuthSession.token_hash == previous_hash)
                )
                if previous_hash is not None
                else None
            )
            user_ids = {external.user_id}
            if previous_user_id is not None:
                user_ids.add(previous_user_id)
            locked_users = db.scalars(
                select(ApplicationUser)
                .where(ApplicationUser.id.in_(user_ids))
                .order_by(ApplicationUser.id)
                .with_for_update()
            ).all()
            user = next(item for item in locked_users if item.id == external.user_id)
            if not user.is_active:
                raise self._inactive()
            user.verified_email = identity.email
            user.email_checked_at = now
            now = self._now()
            if identity.expires_at <= now:
                raise InvalidIdentity()
            if mfa_user is not None and (user.id != mfa_user or previous_hash is None):
                raise InvalidSession()
            if previous_hash is not None:
                previous = db.scalar(
                    select(AuthSession)
                    .where(AuthSession.token_hash == previous_hash)
                    .with_for_update()
                )
                if mfa_user is not None:
                    if (
                        previous is None
                        or previous.user_id != user.id
                        or previous.purpose != "standard"
                    ):
                        raise InvalidSession()
                    self._live(previous, user.is_active, now)
                if previous is not None and previous.revoked_at is None:
                    self._revoke_record(db, previous, now, "reauthentication")
            record = AuthSession(
                id=uuid4(),
                user_id=user.id,
                external_identity_id=external.id,
                token_hash=token_hash,
                access_token_ciphertext=access_ciphertext,
                refresh_token_ciphertext=refresh_ciphertext,
                provider_session_id=identity.session_id,
                aal=identity.aal,
                mfa_verified_at=identity.mfa_verified_at,
                purpose=purpose,
                created_at=now,
                last_seen_at=now,
                absolute_expires_at=now + timedelta(seconds=self.policy.absolute_seconds),
                access_expires_at=identity.expires_at,
                last_provider_check_at=now,
            )
            if mfa_user is not None:
                db.execute(
                    update(AuthSession)
                    .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                    .values(revoked_at=now, refresh_owner=None, refresh_until=None)
                )
                self._audit(db, user.id, user.id, "mfa.verified", now)
            db.add(record)
            self._audit(db, user.id, record.id, "session.established", now, purpose=purpose)
            result = self._result(record, user, opaque_token, now)
        return result

    @staticmethod
    def _check_identity(first: VerifiedIdentity, second: VerifiedIdentity) -> None:
        if (
            first.issuer != second.issuer
            or first.subject != second.subject
            or first.session_id != second.session_id
            or first.aal != second.aal
            or first.expires_at != second.expires_at
            or first.email != second.email
            or second.aal not in {"aal1", "aal2"}
        ):
            raise InvalidIdentity()

    @staticmethod
    def _inactive() -> ApiError:
        return ApiError(403, "ACCOUNT_INACTIVE", "This account is inactive.")

    def _result(
        self, record: AuthSession, user: ApplicationUser, opaque_token: str, now: datetime
    ) -> SessionResult:
        return SessionResult(
            user_id=user.id,
            role=user.role,
            aal=record.aal,
            purpose=record.purpose,
            expires_at=min(
                record.absolute_expires_at, now + timedelta(seconds=self.policy.idle_seconds)
            ),
            csrf_token=self.cipher.csrf_token(opaque_token),
            opaque_token=opaque_token,
            mfa_verified_at=record.mfa_verified_at,
        )

    def _read(self, token_hash: str) -> _Snapshot:
        with self.database.session() as db:
            row = db.execute(
                select(AuthSession, ApplicationUser, ExternalIdentity)
                .join(ApplicationUser, ApplicationUser.id == AuthSession.user_id)
                .join(ExternalIdentity, ExternalIdentity.id == AuthSession.external_identity_id)
                .where(AuthSession.token_hash == token_hash)
            ).one_or_none()
            if row is None:
                raise InvalidSession()
            record, user, external = row
            return _Snapshot(
                id=record.id,
                user_id=user.id,
                external_identity_id=external.id,
                role=user.role,
                is_active=user.is_active,
                issuer=external.issuer,
                subject=external.subject,
                token_hash=record.token_hash,
                access_token_ciphertext=record.access_token_ciphertext,
                refresh_token_ciphertext=record.refresh_token_ciphertext,
                provider_session_id=record.provider_session_id,
                aal=record.aal,
                purpose=record.purpose,
                last_seen_at=record.last_seen_at,
                absolute_expires_at=record.absolute_expires_at,
                access_expires_at=record.access_expires_at,
                last_provider_check_at=record.last_provider_check_at,
                revoked_at=record.revoked_at,
                refresh_owner=record.refresh_owner,
                refresh_until=record.refresh_until,
            )

    def _live(self, record: AuthSession | _Snapshot, active: bool, now: datetime) -> None:
        if record.revoked_at is not None:
            raise InvalidSession()
        if not active:
            raise self._inactive()
        if (
            record.purpose not in {"standard", "recovery"}
            or record.absolute_expires_at <= now
            or record.last_seen_at + timedelta(seconds=self.policy.idle_seconds) <= now
        ):
            raise InvalidSession()

    def _needs_refresh(self, snapshot: AuthSession | _Snapshot, now: datetime) -> bool:
        return snapshot.access_expires_at <= now + timedelta(
            seconds=self.policy.refresh_margin_seconds
        )

    def _needs_check(self, snapshot: AuthSession | _Snapshot, now: datetime) -> bool:
        return (
            snapshot.last_provider_check_at + timedelta(seconds=self.policy.revalidate_seconds)
            <= now
        )

    @staticmethod
    def _matches(snapshot: _Snapshot, identity: VerifiedIdentity) -> bool:
        return (
            snapshot.issuer == identity.issuer
            and snapshot.subject == identity.subject
            and snapshot.provider_session_id == identity.session_id
            and snapshot.aal == identity.aal
        )

    def _revoke_record(self, db: Session, record: AuthSession, now: datetime, reason: str) -> None:
        if record.revoked_at is None:
            record.revoked_at = now
            record.refresh_owner = None
            record.refresh_until = None
            self._audit(db, record.user_id, record.id, "session.revoked", now, reason=reason)

    def _invalidate(self, session_id: UUID, reason: str) -> None:
        with self.database.session() as db, db.begin():
            user_id = db.scalar(select(AuthSession.user_id).where(AuthSession.id == session_id))
            if user_id is None:
                return
            db.scalar(
                select(ApplicationUser).where(ApplicationUser.id == user_id).with_for_update()
            )
            record = db.scalar(
                select(AuthSession).where(AuthSession.id == session_id).with_for_update()
            )
            if record is not None:
                self._revoke_record(db, record, self._now(), reason)

    def _locked(self, db: Session, snapshot: _Snapshot) -> tuple[AuthSession, ApplicationUser]:
        # All completion paths lock user before session. Role/suspension updates use that boundary.
        user = db.scalar(
            select(ApplicationUser).where(ApplicationUser.id == snapshot.user_id).with_for_update()
        )
        record = db.scalar(
            select(AuthSession).where(AuthSession.id == snapshot.id).with_for_update()
        )
        if (
            user is None
            or record is None
            or record.user_id != snapshot.user_id
            or record.external_identity_id != snapshot.external_identity_id
            or record.token_hash != snapshot.token_hash
        ):
            raise InvalidSession()
        self._live(record, user.is_active, self._now())
        return record, user

    def _claim(self, snapshot: _Snapshot, owner: UUID) -> bool:
        with self.database.session() as db, db.begin():
            record, _ = self._locked(db, snapshot)
            now = self._now()
            if (
                record.refresh_owner is not None
                or record.access_token_ciphertext != snapshot.access_token_ciphertext
                or record.last_provider_check_at != snapshot.last_provider_check_at
            ):
                return False
            if not (self._needs_refresh(record, now) or self._needs_check(record, now)):
                return False
            claimed = db.scalar(
                update(AuthSession)
                .where(AuthSession.id == record.id, AuthSession.refresh_owner.is_(None))
                .values(
                    refresh_owner=owner,
                    refresh_until=now + timedelta(seconds=self.policy.refresh_lease_seconds),
                )
                .returning(AuthSession.id)
            )
            return claimed is not None

    def _release(self, session_id: UUID, owner: UUID) -> None:
        with self.database.session() as db, db.begin():
            db.execute(
                update(AuthSession)
                .where(AuthSession.id == session_id, AuthSession.refresh_owner == owner)
                .values(refresh_owner=None, refresh_until=None)
            )

    def authenticate(self, opaque_token: str) -> SessionResult:
        token_hash = hash_token(opaque_token)
        deadline = time.monotonic() + self.policy.refresh_wait_seconds
        while True:
            snapshot = self._read(token_hash)
            now = self._now()
            try:
                self._live(snapshot, snapshot.is_active, now)
            except (InvalidSession, ApiError):
                self._invalidate(snapshot.id, "expired_or_inactive")
                raise
            if snapshot.refresh_owner is not None:
                if snapshot.refresh_until is None or snapshot.refresh_until <= now:
                    # A crashed refresher may have consumed the token; never steal its lease.
                    self._invalidate(snapshot.id, "refresh_lease_expired")
                    raise InvalidSession()
                self._wait(deadline)
                continue
            refresh = self._needs_refresh(snapshot, now)
            revalidate = self._needs_check(snapshot, now)
            if refresh or revalidate:
                owner = uuid4()
                if not self._claim(snapshot, owner):
                    self._wait(deadline)
                    continue
                return self._provider_update(snapshot, opaque_token, owner, refresh)
            try:
                access_token = self.cipher.decrypt(snapshot.access_token_ciphertext)
                identity = self.provider.verify(access_token)
                if (
                    not self._matches(snapshot, identity)
                    or identity.expires_at != snapshot.access_expires_at
                    or identity.expires_at <= self._now()
                ):
                    raise InvalidIdentity()
            except InvalidIdentity:
                self._invalidate(snapshot.id, "provider_rejected")
                raise InvalidSession() from None
            # Provider verification may load JWKS. No transaction or row lock is held above.
            with self.database.session() as db, db.begin():
                record, user = self._locked(db, snapshot)
                if (
                    record.refresh_owner is not None
                    or record.access_token_ciphertext != snapshot.access_token_ciphertext
                    or record.last_provider_check_at != snapshot.last_provider_check_at
                    or self._needs_check(record, self._now())
                    or self._needs_refresh(record, self._now())
                ):
                    retry = True
                else:
                    now = self._now()
                    record.last_seen_at = max(record.last_seen_at, now)
                    result = self._result(record, user, opaque_token, now)
                    retry = False
            if not retry:
                return result
            self._wait(deadline)

    @staticmethod
    def _wait(deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderUnavailable()
        time.sleep(min(0.025, remaining))

    def _provider_update(
        self, snapshot: _Snapshot, opaque_token: str, owner: UUID, refresh: bool
    ) -> SessionResult:
        try:
            access_token = self.cipher.decrypt(snapshot.access_token_ciphertext)
            if refresh:
                if snapshot.access_expires_at > self._now():
                    old_identity = self.provider.verify(access_token)
                    if (
                        not self._matches(snapshot, old_identity)
                        or old_identity.expires_at != snapshot.access_expires_at
                    ):
                        raise InvalidIdentity()
                refresh_token = self.cipher.decrypt(snapshot.refresh_token_ciphertext)
                tokens = self.provider.refresh(refresh_token)
                verified = self.provider.verify(tokens.access_token)
                identity = self.provider.revalidate(tokens.access_token)
                self._check_identity(verified, identity)
                access_ciphertext = self.cipher.encrypt(tokens.access_token)
                refresh_ciphertext = self.cipher.encrypt(tokens.refresh_token)
            else:
                identity = self.provider.revalidate(access_token)
                access_ciphertext = snapshot.access_token_ciphertext
                refresh_ciphertext = snapshot.refresh_token_ciphertext
            if (
                not self._matches(snapshot, identity)
                or not identity.email_verified
                or identity.expires_at <= self._now()
                or (not refresh and identity.expires_at != snapshot.access_expires_at)
            ):
                raise InvalidIdentity()
        except InvalidIdentity:
            self._invalidate(snapshot.id, "provider_rejected")
            raise InvalidSession() from None
        except ProviderUnavailable:
            if refresh:
                # An HTTP timeout may have consumed a rotating refresh token already.
                self._invalidate(snapshot.id, "refresh_uncertain")
            else:
                self._release(snapshot.id, owner)
            raise
        with self.database.session() as db, db.begin():
            record, user = self._locked(db, snapshot)
            now = self._now()
            if (
                record.refresh_owner != owner
                or record.refresh_until is None
                or record.refresh_until <= now
                or record.access_token_ciphertext != snapshot.access_token_ciphertext
                or identity.expires_at <= now
            ):
                # Failure is persisted below, outside the rolled-back transaction.
                lost_lease = True
            else:
                lost_lease = False
                record.access_token_ciphertext = access_ciphertext
                record.refresh_token_ciphertext = refresh_ciphertext
                record.access_expires_at = identity.expires_at
                record.last_provider_check_at = now
                user.verified_email = identity.email
                user.email_checked_at = now
                record.last_seen_at = max(record.last_seen_at, now)
                record.refresh_owner = None
                record.refresh_until = None
                if refresh:
                    self._audit(db, user.id, record.id, "session.refreshed", now)
                result = self._result(record, user, opaque_token, now)
        if lost_lease:
            self._invalidate(snapshot.id, "refresh_lease_expired")
            raise InvalidSession()
        return result

    def logout(self, opaque_token: str) -> None:
        """Local revocation is idempotent and never waits on the provider."""
        try:
            token_hash = hash_token(opaque_token)
        except InvalidSession:
            return
        with self.database.session() as db, db.begin():
            user_id = db.scalar(
                select(AuthSession.user_id).where(AuthSession.token_hash == token_hash)
            )
            if user_id is None:
                return
            db.scalar(
                select(ApplicationUser).where(ApplicationUser.id == user_id).with_for_update()
            )
            record = db.scalar(
                select(AuthSession).where(AuthSession.token_hash == token_hash).with_for_update()
            )
            if record is not None:
                self._revoke_record(db, record, self._now(), "logout")

    def revoke_user_sessions(self, user_id: UUID) -> int:
        """Internal hook for protected role/suspension use cases; not a public admin API."""
        with self.database.session() as db, db.begin():
            user = db.scalar(
                select(ApplicationUser).where(ApplicationUser.id == user_id).with_for_update()
            )
            if user is None:
                return 0
            now = self._now()
            ids = db.scalars(
                update(AuthSession)
                .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=now, refresh_owner=None, refresh_until=None)
                .returning(AuthSession.id)
            ).all()
            if ids:
                self._audit(
                    db,
                    user_id,
                    user_id,
                    "session.user_revoked",
                    now,
                    reason="access_change",
                    count=len(ids),
                )
            return len(ids)
