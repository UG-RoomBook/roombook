from typing import cast

from fastapi import Request

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.identity.crypto import TokenCipher
from app.modules.identity.service import SessionService


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
