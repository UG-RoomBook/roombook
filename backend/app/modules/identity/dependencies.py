import secrets
from typing import Annotated, cast

from fastapi import Depends, Header, Request, Security
from fastapi.security import APIKeyCookie

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.identity.crypto import TokenCipher
from app.modules.identity.service import InvalidSession, SessionResult, SessionService
from app.modules.identity.types import InvalidIdentity, ProviderUnavailable


def auth_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_session_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "identity_sessions", None)
    if not isinstance(service, SessionService):
        raise ApiError(503, "AUTH_NOT_CONFIGURED", "Account services are not available.")
    return service


def get_token_cipher(request: Request) -> TokenCipher:
    cipher = getattr(request.app.state, "identity_cipher", None)
    if not isinstance(cipher, TokenCipher):
        raise ApiError(503, "AUTH_NOT_CONFIGURED", "Account services are not available.")
    return cipher


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


def session_token(request: Request, settings: Settings) -> str | None:
    values = request.cookies.get(settings.auth_cookie_name)
    if values is None or len(values) != 43:
        return None
    return values


def authenticated_session(
    request: Request, settings: Settings, service: SessionService
) -> SessionResult:
    opaque = session_token(request, settings)
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


def require_booking_session(
    request: Request,
    settings: SettingsDependency,
    service: ServiceDependency,
    _credential: CookieCredential,
    origin: OriginHeader = None,
    csrf_token: CsrfHeader = None,
) -> SessionResult:
    result = authenticated_session(request, settings, service)
    if (
        origin != settings.auth_site_url
        or request.headers.get("Sec-Fetch-Site") == "cross-site"
        or not secrets.compare_digest((csrf_token or "").encode(), result.csrf_token.encode())
    ):
        raise ApiError(403, "CSRF_REJECTED", "Reload the page and try again.")
    return result
