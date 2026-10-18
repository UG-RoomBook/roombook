import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request, Response, Security
from fastapi.security import APIKeyCookie

from app.core.config import Settings
from app.core.errors import ApiError, ErrorResponse
from app.modules.identity.crypto import TokenCipher
from app.modules.identity.dependencies import auth_settings, get_session_service, get_token_cipher
from app.modules.identity.schemas import SessionResponse, SessionUser
from app.modules.identity.service import InvalidSession, SessionResult, SessionService
from app.modules.identity.types import InvalidIdentity, ProviderUnavailable

router = APIRouter(prefix="/api/v1/auth", tags=["Identity"])
SettingsDependency = Annotated[Settings, Depends(auth_settings)]
ServiceDependency = Annotated[SessionService, Depends(get_session_service)]
CipherDependency = Annotated[TokenCipher, Depends(get_token_cipher)]
CookieCredential = Annotated[
    str | None,
    Security(
        APIKeyCookie(
            name="__Host-roombook_session",
            scheme_name="SessionCookie",
            auto_error=False,
            description=(
                "Opaque HttpOnly session cookie. Loopback development may use roombook_session."
            ),
        )
    ),
]
CsrfHeader = Annotated[
    str | None,
    Header(
        alias="X-CSRF-Token", max_length=256, description="CSRF value from the current session."
    ),
]
OriginHeader = Annotated[
    str | None, Header(alias="Origin", description="Exact configured RoomBook application origin.")
]


def _token(request: Request, settings: Settings) -> str | None:
    values = request.cookies.get(settings.auth_cookie_name)
    if values is None or len(values) != 43:
        return None
    return values


def _authenticated(request: Request, settings: Settings, service: SessionService) -> SessionResult:
    opaque = _token(request, settings)
    if opaque is None:
        raise ApiError(401, "AUTH_REQUIRED", "Sign in to continue.")
    try:
        result = service.authenticate(opaque)
    except (InvalidSession, InvalidIdentity):
        raise ApiError(401, "AUTH_REQUIRED", "Sign in to continue.") from None
    except ProviderUnavailable:
        raise ApiError(
            503, "IDENTITY_UNAVAILABLE", "Account services are temporarily unavailable."
        ) from None
    if result.purpose != "standard":
        raise ApiError(403, "RECOVERY_RESTRICTED", "Complete account recovery to continue.")
    return result


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
    result = _authenticated(request, settings, service)
    # These values are controlled by the database and verified provider claims.
    role: Literal["Member", "Admin"] = "Admin" if result.role == "Admin" else "Member"
    aal: Literal["aal1", "aal2"] = "aal2" if result.aal == "aal2" else "aal1"
    return SessionResponse(
        user=SessionUser(id=result.user_id, role=role),
        aal=aal,
        expires_at=result.expires_at,
        csrf_token=result.csrf_token,
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
    opaque = _token(request, settings)
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
