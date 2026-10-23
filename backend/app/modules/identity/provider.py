"""A stateless Supabase HTTP adapter with a bounded, pinned-issuer JWKS cache."""

import json
import math
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.modules.identity.types import (
    InvalidIdentity,
    ProviderTokens,
    ProviderUnavailable,
    VerifiedIdentity,
)

_MAX_RESPONSE_BYTES = 65_536
_MAX_TOKEN_LENGTH = 16_384
_UNKNOWN_KEY_RETRY_SECONDS = 30
_FAILED_FETCH_RETRY_SECONDS = 5
_REQUIRED_CLAIMS = [
    "iss",
    "aud",
    "exp",
    "iat",
    "sub",
    "role",
    "aal",
    "session_id",
    "email",
    "is_anonymous",
]


class SupabaseProvider:
    def __init__(
        self,
        url: str,
        publishable_key: str,
        *,
        client: httpx.Client | None = None,
        jwks_ttl_seconds: int = 300,
        timeout_seconds: float = 5.0,
    ) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in url)
        ):
            raise ValueError("Identity provider URL must be an HTTPS origin.")
        if not publishable_key or any(character.isspace() for character in publishable_key):
            raise ValueError("Identity provider publishable key is invalid.")
        if not 1 <= jwks_ttl_seconds <= 600:
            raise ValueError("Identity signing-key cache duration is invalid.")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30:
            raise ValueError("Identity provider timeout is invalid.")
        self._issuer = url.rstrip("/") + "/auth/v1"
        self._publishable_key = publishable_key
        self._timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self._owns_client = client is None
        self._ttl = jwks_ttl_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._keys_until = 0.0
        self._next_unknown_refresh_at = 0.0
        self._fetch_failed_until = 0.0
        self._keys_lock = threading.Lock()

    def verify(self, access_token: str) -> VerifiedIdentity:
        if not access_token or len(access_token) > _MAX_TOKEN_LENGTH:
            raise InvalidIdentity()
        try:
            header = jwt.get_unverified_header(access_token)
            algorithm = header.get("alg")
            kid = header.get("kid")
            if (
                algorithm not in ("ES256", "RS256")
                or not isinstance(kid, str)
                or not 1 <= len(kid) <= 128
                or header.get("crit")
                or header.get("b64") is False
            ):
                raise InvalidIdentity()
            key = self._signing_key(kid)
            if key.algorithm_name != algorithm:
                raise InvalidIdentity()
            claims = jwt.decode(
                access_token,
                key.key,
                algorithms=[algorithm],
                audience="authenticated",
                issuer=self._issuer,
                options={"require": _REQUIRED_CLAIMS},
            )
            return self._identity(claims)
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
            raise InvalidIdentity() from None

    def revalidate(self, access_token: str) -> VerifiedIdentity:
        identity = self.verify(access_token)
        user = self._request_json(
            "GET", "/user", authorization=access_token, invalid_statuses=(400, 401, 403, 404, 422)
        )
        if (
            user.get("id") != identity.subject
            or user.get("email") != identity.email
            or user.get("aud") != "authenticated"
            or user.get("is_anonymous") is not False
        ):
            raise InvalidIdentity()
        confirmed_at = user.get("email_confirmed_at")
        if confirmed_at is not None:
            try:
                if not isinstance(confirmed_at, str):
                    raise ValueError
                confirmed = datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
                if confirmed.tzinfo is None or confirmed > datetime.now(UTC):
                    raise ValueError
            except ValueError:
                raise InvalidIdentity() from None
        # User metadata is client-editable. Only the live server's confirmation field is authority.
        return replace(identity, email_verified=confirmed_at is not None)

    def refresh(self, refresh_token: str) -> ProviderTokens:
        if not refresh_token or len(refresh_token) > _MAX_TOKEN_LENGTH:
            raise InvalidIdentity()
        response = self._request_json(
            "POST",
            "/token?grant_type=refresh_token",
            payload={"refresh_token": refresh_token},
            invalid_statuses=(400, 401, 403, 404, 422),
        )
        access = response.get("access_token")
        refresh = response.get("refresh_token")
        if (
            not isinstance(access, str)
            or not access
            or len(access) > _MAX_TOKEN_LENGTH
            or not isinstance(refresh, str)
            or not refresh
            or len(refresh) > _MAX_TOKEN_LENGTH
            or response.get("token_type") != "bearer"
        ):
            raise ProviderUnavailable()
        self.verify(access)
        return ProviderTokens(access_token=access, refresh_token=refresh)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def account_request(
        self, method: str, path: str, payload: dict[str, str], access: str | None = None
    ) -> dict[str, object]:
        allowed = {
            ("POST", "/signup"),
            ("POST", "/recover"),
            ("POST", "/resend"),
            ("POST", "/token?grant_type=password"),
            ("POST", "/verify"),
            ("PUT", "/user"),
        }
        if (method, path) not in allowed:
            raise ValueError("Unsupported account operation.")
        return self._request_json(
            method,
            path,
            payload=payload,
            authorization=access,
            invalid_statuses=(400, 401, 403, 404, 422),
        )

    def mfa_request(
        self,
        method: str,
        operation: str,
        access: str,
        payload: dict[str, str] | None = None,
        factor_id: UUID | None = None,
    ) -> dict[str, object]:
        paths = {("GET", "list"): "/user", ("POST", "enroll"): "/factors"}
        if factor_id is not None:
            paths.update(
                {
                    ("POST", "challenge"): f"/factors/{factor_id}/challenge",
                    ("POST", "verify"): f"/factors/{factor_id}/verify",
                    ("DELETE", "remove"): f"/factors/{factor_id}",
                }
            )
        path = paths.get((method, operation))
        if path is None:
            raise ValueError("Unsupported MFA operation.")
        return self._request_json(
            method,
            path,
            authorization=access,
            payload=payload,
            invalid_statuses=(400, 401, 403, 404, 422, 429),
        )

    def _identity(self, claims: dict[str, object]) -> VerifiedIdentity:
        subject = claims["sub"]
        session_id = claims["session_id"]
        email = claims["email"]
        exp, issued = claims["exp"], claims["iat"]
        if (
            claims["iss"] != self._issuer
            or claims["aud"] not in ("authenticated", ["authenticated"])
            or claims["role"] != "authenticated"
            or claims["is_anonymous"] is not False
            or claims["aal"] not in ("aal1", "aal2")
            or not isinstance(subject, str)
            or not isinstance(session_id, str)
            or not isinstance(email, str)
            or not 1 <= len(email) <= 320
            or any(ord(character) < 32 for character in email)
            or type(exp) is not int
            or type(issued) is not int
        ):
            raise InvalidIdentity()
        if UUID(subject).int == 0 or UUID(session_id).int == 0 or exp <= issued:
            raise InvalidIdentity()
        mfa_at = None
        amr = claims.get("amr", [])
        if claims["aal"] == "aal2" and isinstance(amr, list):
            times = [
                entry["timestamp"]
                for entry in amr
                if isinstance(entry, dict)
                and entry.get("method") == "totp"
                and type(entry.get("timestamp")) is int
                and 0 < entry["timestamp"] <= issued
            ]
            if times:
                mfa_at = datetime.fromtimestamp(max(times), UTC)
        return VerifiedIdentity(
            issuer=self._issuer,
            subject=subject,
            session_id=session_id,
            email=email,
            email_verified=False,
            aal=str(claims["aal"]),
            expires_at=datetime.fromtimestamp(exp, UTC),
            mfa_verified_at=mfa_at,
        )

    def _signing_key(self, kid: str) -> jwt.PyJWK:
        with self._keys_lock:
            now = time.monotonic()
            expired = now >= self._keys_until
            if not expired and kid in self._keys:
                return self._keys[kid]
            if now < self._fetch_failed_until:
                raise ProviderUnavailable()
            if not expired and now < self._next_unknown_refresh_at:
                raise InvalidIdentity()
            self._next_unknown_refresh_at = now + _UNKNOWN_KEY_RETRY_SECONDS
            try:
                document = self._request_json("GET", "/.well-known/jwks.json")
                keys = self._parse_keys(document)
            except ProviderUnavailable:
                self._fetch_failed_until = time.monotonic() + _FAILED_FETCH_RETRY_SECONDS
                raise
            self._keys = keys
            self._keys_until = time.monotonic() + self._ttl
            if kid not in keys:
                raise InvalidIdentity()
            return keys[kid]

    def _parse_keys(self, document: dict[str, object]) -> dict[str, jwt.PyJWK]:
        raw_keys = document.get("keys")
        if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 16:
            raise ProviderUnavailable()
        result: dict[str, jwt.PyJWK] = {}
        try:
            for item in raw_keys:
                if not isinstance(item, dict):
                    raise ValueError
                kid, algorithm = item.get("kid"), item.get("alg")
                if (
                    not isinstance(kid, str)
                    or not 1 <= len(kid) <= 128
                    or kid in result
                    or algorithm not in ("ES256", "RS256")
                    or item.get("use", "sig") != "sig"
                    or item.get("key_ops", ["verify"]) != ["verify"]
                    or any(name in item for name in ("d", "p", "q", "dp", "dq", "qi", "k"))
                ):
                    raise ValueError
                key = jwt.PyJWK.from_dict(item, algorithm=algorithm)
                if algorithm == "ES256" and not (
                    isinstance(key.key, ec.EllipticCurvePublicKey)
                    and isinstance(key.key.curve, ec.SECP256R1)
                ):
                    raise ValueError
                if algorithm == "RS256" and not (
                    isinstance(key.key, rsa.RSAPublicKey) and key.key.key_size >= 2048
                ):
                    raise ValueError
                result[kid] = key
        except (ValueError, TypeError, jwt.PyJWTError):
            raise ProviderUnavailable() from None
        return result

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        authorization: str | None = None,
        payload: dict[str, str] | None = None,
        invalid_statuses: tuple[int, ...] = (),
    ) -> dict[str, object]:
        headers = {"apikey": self._publishable_key, "accept": "application/json"}
        if authorization is not None:
            headers["authorization"] = "Bearer " + authorization
        try:
            started = time.monotonic()
            with self._client.stream(
                method,
                self._issuer + path,
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code in invalid_statuses:
                    raise InvalidIdentity()
                if response.status_code != 200:
                    raise ProviderUnavailable()
                if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise ProviderUnavailable()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if (
                        len(content) > _MAX_RESPONSE_BYTES
                        or time.monotonic() - started > self._timeout_seconds
                    ):
                        raise ProviderUnavailable()
                data: object = json.loads(content)
                if not isinstance(data, dict):
                    raise ProviderUnavailable()
                return data
        except (httpx.HTTPError, ValueError, UnicodeError, OSError):
            raise ProviderUnavailable() from None
