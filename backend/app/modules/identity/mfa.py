"""TOTP broker. Provider tokens stay encrypted on the server; secrets are never audited."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update

from app.core.errors import ApiError, ErrorResponse
from app.modules.admin.access import recent_mfa
from app.modules.admin.schemas import ReasonInput
from app.modules.identity.account_router import (
    AccountsDependency,
    MessageResponse,
    authenticated_token,
    rate,
)
from app.modules.identity.accounts import AccountService
from app.modules.identity.dependencies import authenticated_session
from app.modules.identity.models import ApplicationUser, AuditEvent, AuthSession
from app.modules.identity.router import set_session_cookie
from app.modules.identity.schemas import SessionResponse, SessionUser
from app.modules.identity.service import InvalidSession, hash_token
from app.modules.identity.types import InvalidIdentity, ProviderUnavailable

router = APIRouter(
    prefix="/api/v1/auth/mfa",
    tags=["MFA"],
    responses={code: {"model": ErrorResponse} for code in (400, 401, 403, 409, 422, 429, 503)},
)


class Factor(BaseModel):
    id: UUID
    friendly_name: str = Field(default="Authenticator", max_length=200)
    factor_type: Literal["totp"]
    status: Literal["verified", "unverified"]


class Factors(BaseModel):
    factors: list[Factor]


class EnrollInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=64)


class Enrollment(BaseModel):
    id: UUID
    secret: str = Field(max_length=256, repr=False)
    qr_code: str = Field(max_length=60_000, repr=False)


class VerifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    factor_id: UUID
    code: str = Field(pattern=r"^\d{6}$", repr=False)


def call(
    service: AccountService,
    method: str,
    operation: str,
    access: str,
    payload: dict[str, str] | None = None,
    factor: UUID | None = None,
) -> dict[str, object]:
    try:
        return service.provider.mfa_request(method, operation, access, payload, factor)
    except InvalidIdentity:
        raise ApiError(
            400, "MFA_REJECTED", "Authenticator request rejected. Check the code and retry."
        ) from None
    except ProviderUnavailable:
        raise ApiError(
            503, "IDENTITY_UNAVAILABLE", "Authenticator services are temporarily unavailable."
        ) from None


def factors(service: AccountService, access: str) -> list[Factor]:
    data = call(service, "GET", "list", access).get("factors", [])
    try:
        if not isinstance(data, list):
            raise ValueError
        return [
            Factor.model_validate(item)
            for item in data
            if isinstance(item, dict) and item.get("factor_type") == "totp"
        ]
    except (ValueError, ValidationError):
        raise ApiError(
            503, "IDENTITY_UNAVAILABLE", "Authenticator details could not be verified."
        ) from None


@router.get("", operation_id="listMfaFactors")
def list_factors(request: Request, service: AccountsDependency) -> Factors:
    actor = authenticated_session(request, request.app.state.settings, service.sessions)
    _, access = service.account_access(actor.opaque_token, "standard")
    return Factors(factors=factors(service, access))


@router.post("/enroll", operation_id="enrollMfaFactor")
def enroll(body: EnrollInput, request: Request, service: AccountsDependency) -> Enrollment:
    opaque = authenticated_token(request, service, "standard")
    actor, access = service.account_access(opaque, "standard")
    rate(request, service, "mfa-enroll", str(actor.user_id))
    if any(f.status == "verified" for f in factors(service, access)):
        recent_mfa(actor.mfa_verified_at, service.sessions._now())
    data = call(
        service,
        "POST",
        "enroll",
        access,
        {"factor_type": "totp", "friendly_name": body.name, "issuer": "RoomBook"},
    )
    totp = data.get("totp")
    if not isinstance(totp, dict):
        raise ApiError(
            503, "IDENTITY_UNAVAILABLE", "Authenticator enrollment could not be verified."
        )
    try:
        result = Enrollment.model_validate({"id": data.get("id"), **totp})
    except ValidationError:
        raise ApiError(
            503, "IDENTITY_UNAVAILABLE", "Authenticator enrollment could not be verified."
        ) from None
    with service.sessions.database.session() as db, db.begin():
        db.add(
            AuditEvent(
                actor_user_id=actor.user_id, target_id=result.id, action="mfa.enrolled", details={}
            )
        )
    return result


@router.post("/verify", operation_id="verifyMfaFactor")
def verify(
    body: VerifyInput, request: Request, response: Response, service: AccountsDependency
) -> SessionResponse:
    opaque = authenticated_token(request, service, "standard")
    actor, access = service.account_access(opaque, "standard")
    rate(request, service, "mfa-verify", str(actor.user_id))
    if not any(f.id == body.factor_id for f in factors(service, access)):
        raise ApiError(400, "MFA_REJECTED", "Choose one of your authenticators.")
    challenge = call(service, "POST", "challenge", access, {}, body.factor_id)
    try:
        challenge_id = str(UUID(str(challenge.get("id"))))
    except ValueError:
        raise ApiError(
            503, "IDENTITY_UNAVAILABLE", "Authenticator challenge could not be verified."
        ) from None
    data = call(
        service,
        "POST",
        "verify",
        access,
        {"challenge_id": challenge_id, "code": body.code},
        body.factor_id,
    )
    try:
        result = service.sessions.establish(
            service._tokens(data), previous_token=opaque, mfa_user=actor.user_id
        )
    except (InvalidIdentity, InvalidSession):
        raise ApiError(
            401, "AUTH_REQUIRED", "Sign in and verify your authenticator again."
        ) from None
    except ProviderUnavailable:
        raise ApiError(
            503, "IDENTITY_UNAVAILABLE", "Authenticator verification could not be completed."
        ) from None
    set_session_cookie(response, request.app.state.settings, result)
    return SessionResponse(
        user=SessionUser(id=result.user_id, role="Admin" if result.role == "Admin" else "Member"),
        aal="aal2",
        expires_at=result.expires_at,
        csrf_token=result.csrf_token,
        mfa_verified_at=result.mfa_verified_at,
    )


@router.post("/{factor_id}/remove", operation_id="removeMfaFactor")
def remove(
    factor_id: UUID, body: ReasonInput, request: Request, service: AccountsDependency
) -> MessageResponse:
    opaque = authenticated_token(request, service, "standard")
    actor, access = service.account_access(opaque, "standard")
    rate(request, service, "mfa-remove", str(actor.user_id))
    failure: ApiError | None = None
    with service.sessions.database.session() as db, db.begin():
        user = db.scalar(
            select(ApplicationUser).where(ApplicationUser.id == actor.user_id).with_for_update()
        )
        record = db.scalar(
            select(AuthSession)
            .where(AuthSession.token_hash == hash_token(opaque))
            .with_for_update()
        )
        now = service.sessions._now()
        if user is None or not user.is_active or record is None or record.revoked_at is not None:
            raise ApiError(401, "AUTH_REQUIRED", "Sign in to continue.")
        try:
            service.sessions._live(record, user.is_active, now)
        except InvalidSession:
            raise ApiError(401, "AUTH_REQUIRED", "Sign in to continue.") from None
        owned = factors(service, access)
        factor = next((f for f in owned if f.id == factor_id), None)
        if factor is None:
            raise ApiError(404, "FACTOR_NOT_FOUND", "Authenticator was not found.")
        if factor.status == "verified":
            recent_mfa(record.mfa_verified_at, now)
            if user.role == "Admin" and sum(f.status == "verified" for f in owned) <= 1:
                raise ApiError(
                    409, "LAST_ADMIN_FACTOR", "Add and verify another authenticator first."
                )
        try:
            call(service, "DELETE", "remove", access, factor=factor_id)
        except ApiError as exc:
            failure = exc
        # Revoke on uncertain outcomes too: removed factors must never leave aal2 access.
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == actor.user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, refresh_owner=None, refresh_until=None)
        )
        db.add(
            AuditEvent(
                actor_user_id=actor.user_id,
                target_id=factor_id,
                action="mfa.removal_uncertain" if failure else "mfa.removed",
                details={"reason": body.reason},
                occurred_at=now,
            )
        )
    if failure:
        raise failure
    return MessageResponse(message="Authenticator removed. Sign in again to continue.")
