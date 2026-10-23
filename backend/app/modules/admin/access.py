"""Application-owned admin authorization, repeated inside every database transaction."""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.identity.dependencies import (
    CookieCredential,
    CsrfHeader,
    OriginHeader,
    ServiceDependency,
    SettingsDependency,
    authenticated_session,
    require_booking_session,
)
from app.modules.identity.models import ApplicationUser, AuthSession
from app.modules.identity.service import SessionResult, SessionService, hash_token


def require_admin(result: SessionResult) -> SessionResult:
    if result.role != "Admin":
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator access is required.")
    if result.aal != "aal2" or result.mfa_verified_at is None:
        raise ApiError(403, "MFA_REQUIRED", "Verify your authenticator to continue.")
    return result


def admin_session(
    request: Request,
    settings: SettingsDependency,
    service: ServiceDependency,
    _credential: CookieCredential,
) -> SessionResult:
    return require_admin(authenticated_session(request, settings, service))


def admin_write(
    request: Request,
    settings: SettingsDependency,
    service: ServiceDependency,
    credential: CookieCredential,
    origin: OriginHeader = None,
    csrf_token: CsrfHeader = None,
) -> SessionResult:
    return require_admin(
        require_booking_session(request, settings, service, credential, origin, csrf_token)
    )


AdminRead = Annotated[SessionResult, Depends(admin_session)]
AdminWrite = Annotated[SessionResult, Depends(admin_write)]


def recent_mfa(verified: datetime | None, now: datetime) -> None:
    if verified is None or not now - timedelta(minutes=10) <= verified <= now:
        raise ApiError(403, "MFA_RECENT_REQUIRED", "Verify your authenticator again before saving.")


def recheck(
    db: Session,
    actor: SessionResult,
    service: SessionService,
    *,
    recent: bool = False,
    exclusive: bool = False,
) -> datetime:
    # A shared user lock coordinates with suspension/demotion, which holds an exclusive lock.
    user = db.scalar(
        select(ApplicationUser)
        .where(ApplicationUser.id == actor.user_id)
        .with_for_update(read=not exclusive)
    )
    now = service._now()
    record = db.scalar(
        select(AuthSession)
        .where(AuthSession.token_hash == hash_token(actor.opaque_token))
        .with_for_update(read=True)
    )
    if (
        user is None
        or not user.is_active
        or record is None
        or record.revoked_at is not None
        or record.user_id != actor.user_id
        or record.purpose != "standard"
        or record.absolute_expires_at <= now
        or record.last_seen_at + timedelta(seconds=service.policy.idle_seconds) <= now
    ):
        raise ApiError(401, "AUTH_REQUIRED", "Sign in to continue.")
    if user.role != "Admin":
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator access is required.")
    if record.aal != "aal2" or record.mfa_verified_at is None:
        raise ApiError(403, "MFA_REQUIRED", "Verify your authenticator to continue.")
    if recent:
        recent_mfa(record.mfa_verified_at, now)
    return now
