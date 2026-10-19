"""Authenticated token encryption and a distinct, keyed session CSRF value."""

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.modules.identity.types import InvalidIdentity


class TokenCipher:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
            raw_key = base64.urlsafe_b64decode(key.encode("ascii"))
        except (ValueError, UnicodeError):
            raise ValueError("Authentication encryption key is invalid.") from None
        self._csrf_key = hmac.digest(raw_key, b"roombook/session-csrf/key/v1", hashlib.sha256)

    def encrypt(self, value: str) -> str:
        if not value or len(value) > 100_000:
            raise InvalidIdentity()
        try:
            return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        except UnicodeError:
            raise InvalidIdentity() from None

    def decrypt(self, value: str) -> str:
        if not value or len(value) > 200_000:
            raise InvalidIdentity()
        try:
            result = self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError):
            raise InvalidIdentity() from None
        if not result:
            raise InvalidIdentity()
        return result

    def csrf_token(self, opaque_token: str) -> str:
        return hmac.new(
            self._csrf_key,
            b"roombook/session-csrf/value/v1\x00" + opaque_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
