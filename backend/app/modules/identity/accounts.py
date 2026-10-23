"""Account use cases. Provider credentials and email-link verification stay on the server."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import DateTime, Integer, String, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, mapped_column

from app.core.errors import ApiError
from app.db.base import Base
from app.modules.identity.provider import SupabaseProvider
from app.modules.identity.service import InvalidSession, SessionResult, SessionService, hash_token
from app.modules.identity.types import InvalidIdentity, ProviderTokens, ProviderUnavailable

LinkType = Literal["email", "signup", "recovery", "email_change"]


class AccountAttempt(Base):
    __tablename__ = "account_attempts"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, index=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)


class AccountService:
    def __init__(self, sessions: SessionService, provider: SupabaseProvider) -> None:
        self.sessions = sessions
        self.provider = provider

    def limit(self, action: str, peer: str, account: str = "") -> None:
        """Shared PostgreSQL counters; never trust caller-controlled forwarding headers."""
        now = datetime.now(UTC)
        bucket = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
        exceeded = False
        with self.sessions.database.session() as db, db.begin():
            db.execute(
                delete(AccountAttempt).where(AccountAttempt.bucket < now - timedelta(hours=1))
            )
            peer_limit, account_limit = (200, 100) if action == "admin-write" else (50, 10)
            for kind, value, maximum in [
                ("peer", peer, peer_limit),
                ("account", account.casefold(), account_limit),
            ]:
                if exceeded or (kind == "account" and not account):
                    break
                key = self.sessions.cipher.csrf_token(f"attempt/{action}/{kind}/{value}")
                statement = insert(AccountAttempt).values(key=key, bucket=bucket, count=1)
                count = db.scalar(
                    statement.on_conflict_do_update(
                        index_elements=["key", "bucket"],
                        set_={"count": AccountAttempt.count + 1},
                    ).returning(AccountAttempt.count)
                )
                exceeded = count is not None and count > maximum
        if exceeded:
            raise ApiError(429, "ACCOUNT_RATE_LIMIT", "Too many attempts. Try again later.")

    def _call(
        self, method: str, path: str, payload: dict[str, str], access: str | None = None
    ) -> dict[str, object]:
        try:
            return self.provider.account_request(method, path, payload, access)
        except InvalidIdentity:
            raise ApiError(
                400, "ACCOUNT_REQUEST_REJECTED", "Check your details or request a new link."
            ) from None
        except ProviderUnavailable:
            raise ApiError(
                503, "IDENTITY_UNAVAILABLE", "Account services are temporarily unavailable."
            ) from None

    @staticmethod
    def _tokens(data: dict[str, object]) -> ProviderTokens:
        access, refresh = data.get("access_token"), data.get("refresh_token")
        if (
            not isinstance(access, str)
            or not access
            or len(access) > 16_384
            or not isinstance(refresh, str)
            or not refresh
            or len(refresh) > 16_384
            or data.get("token_type") != "bearer"
        ):
            raise ApiError(
                503, "IDENTITY_UNAVAILABLE", "Account services are temporarily unavailable."
            )
        return ProviderTokens(access, refresh)

    def establish(
        self, data: dict[str, object], previous: str | None, purpose: str = "standard"
    ) -> SessionResult:
        try:
            return self.sessions.establish(
                self._tokens(data), previous_token=previous, purpose=purpose
            )
        except (InvalidIdentity, InvalidSession):
            raise ApiError(
                401, "SIGN_IN_REJECTED", "Check your credentials and verify your email."
            ) from None
        except ProviderUnavailable:
            raise ApiError(
                503, "IDENTITY_UNAVAILABLE", "Account services are temporarily unavailable."
            ) from None

    def login(self, email: str, password: str, previous: str | None) -> SessionResult:
        try:
            data = self._call(
                "POST", "/token?grant_type=password", {"email": email, "password": password}
            )
        except ApiError as exc:
            if exc.status_code == 400:
                raise ApiError(
                    401, "SIGN_IN_REJECTED", "Check your credentials and verify your email."
                ) from None
            raise
        return self.establish(data, previous)

    def send(self, action: str, email: str, password: str = "") -> None:
        paths = {"register": "/signup", "recover": "/recover", "resend": "/resend"}
        payload = {"email": email}
        if action == "register":
            payload["password"] = password
        if action == "resend":
            payload["type"] = "signup"
        try:
            self._call("POST", paths[action], payload)
        except ApiError as exc:
            # Never reveal whether an address is registered/verified, including provider errors.
            if exc.status_code != 400:
                raise

    def confirm(
        self, token_hash: str, kind: LinkType, previous: str | None
    ) -> SessionResult | None:
        data = self._call("POST", "/verify", {"token_hash": token_hash, "type": kind})
        if kind != "recovery":
            # Confirmation must not silently switch the browser into the linked account.
            # Secure email change may also require confirmation from both mailboxes.
            return None
        return self.establish(data, previous, "recovery")

    def account_access(self, opaque: str, purpose: str) -> tuple[SessionResult, str]:
        try:
            result = self.sessions.authenticate(opaque)
            if result.purpose != purpose:
                raise ApiError(403, "SESSION_RESTRICTED", "Use the appropriate account flow.")
            snapshot = self.sessions._read(hash_token(opaque))
            return result, self.sessions.cipher.decrypt(snapshot.access_token_ciphertext)
        except (InvalidIdentity, InvalidSession):
            raise ApiError(
                401, "AUTH_REQUIRED", "Sign in or request a new recovery link."
            ) from None
        except ProviderUnavailable:
            raise ApiError(
                503, "IDENTITY_UNAVAILABLE", "Account services are temporarily unavailable."
            ) from None

    def change(self, opaque: str, value: str, *, recovery: bool) -> None:
        result, access = self.account_access(opaque, "recovery" if recovery else "standard")
        try:
            self._call("PUT", "/user", {"password" if recovery else "email": value}, access)
        finally:
            # Success or an uncertain upstream result must not leave prior local sessions active.
            self.sessions.revoke_user_sessions(result.user_id)
