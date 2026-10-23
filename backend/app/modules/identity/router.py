import secrets
from typing import Literal

from fastapi import APIRouter, Request, Response

from app.core.config import Settings
from app.core.errors import ApiError, ErrorResponse
from app.modules.identity.dependencies import (
    CipherDependency,
    CookieCredential,
    CsrfHeader,
    OriginHeader,
    ServiceDependency,
    SettingsDependency,
    authenticated_session,
    session_token,
)
from app.modules.identity.schemas import SessionResponse, SessionUser
from app.modules.identity.service import SessionResult

router = APIRouter(prefix="/api/v1/auth", tags=["Identity"])


@router.get(
    "/session",
    operation_id="getCurrentSession",
    response_model=SessionResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Sign-in required"},
        403: {"model": ErrorResponse, "description": "Restricted or inactive account"},
        503: {"model": ErrorResponse, "description": "Account service unavailable"},
    },
)
def current_session(
    request: Request,
    settings: SettingsDependency,
    service: ServiceDependency,
    _credential: CookieCredential,
) -> SessionResponse:
    result = authenticated_session(request, settings, service)
    # These values are controlled by the database and verified provider claims.
    role: Literal["Member", "Admin"] = "Admin" if result.role == "Admin" else "Member"
    aal: Literal["aal1", "aal2"] = "aal2" if result.aal == "aal2" else "aal1"
    return SessionResponse(
        user=SessionUser(id=result.user_id, role=role),
        aal=aal,
        expires_at=result.expires_at,
        csrf_token=result.csrf_token,
        mfa_verified_at=result.mfa_verified_at,
    )


def set_session_cookie(response: Response, settings: Settings, result: SessionResult) -> None:
    """Used by future account authentication after service-owned session rotation."""
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=result.opaque_token,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=settings.auth_absolute_seconds,
    )


@router.post(
    "/logout",
    operation_id="logoutCurrentSession",
    status_code=204,
    responses={
        403: {"model": ErrorResponse, "description": "Origin or CSRF check failed"},
        503: {"model": ErrorResponse, "description": "Account service unavailable"},
    },
)
def logout(
    request: Request,
    settings: SettingsDependency,
    service: ServiceDependency,
    cipher: CipherDependency,
    _credential: CookieCredential,
    origin: OriginHeader = None,
    csrf_token: CsrfHeader = None,
) -> Response:
    if origin != settings.auth_site_url or request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise ApiError(403, "CSRF_REJECTED", "Reload the page and try again.")
    opaque = session_token(request, settings)
    if opaque is not None:
        supplied = csrf_token or ""
        expected = cipher.csrf_token(opaque)
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            raise ApiError(403, "CSRF_REJECTED", "Reload the page and try again.")
        # Immediate local revocation must not depend on provider availability.
        service.logout(opaque)
    response = Response(status_code=204)
    response.delete_cookie(
        key=settings.auth_cookie_name,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response
