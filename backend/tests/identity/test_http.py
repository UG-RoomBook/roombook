import logging
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import Response
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.modules.identity.crypto import TokenCipher
from app.modules.identity.dependencies import get_session_service, get_token_cipher
from app.modules.identity.router import set_session_cookie
from app.modules.identity.security import IdentityAccessLogFilter
from app.modules.identity.service import InvalidSession, SessionResult, SessionService
from app.modules.identity.types import InvalidIdentity, ProviderUnavailable

ORIGIN = "https://roombook.example"
TOKEN_A = "a" * 43
TOKEN_B = "b" * 43


class StubSessions:
    def __init__(self, cipher: TokenCipher) -> None:
        self.results = {
            token: SessionResult(
                user_id=uuid4(),
                role="Member",
                aal="aal1",
                purpose="standard",
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
                csrf_token=cipher.csrf_token(token),
                opaque_token=token,
            )
            for token in (TOKEN_A, TOKEN_B)
        }
        self.failure: Exception | None = None
        self.revoked: list[str] = []

    def authenticate(self, token: str) -> SessionResult:
        if self.failure is not None:
            raise self.failure
        if token not in self.results or token in self.revoked:
            raise InvalidSession()
        return self.results[token]

    def logout(self, token: str) -> None:
        self.revoked.append(token)


@pytest.fixture
def http_identity() -> tuple[TestClient, StubSessions, TokenCipher]:
    settings = Settings(_env_file=None, database_url=None, auth_enabled=False, auth_site_url=ORIGIN)
    app = create_app(settings)
    cipher = TokenCipher(Fernet.generate_key().decode())
    service = StubSessions(cipher)
    app.dependency_overrides[get_session_service] = lambda: cast(SessionService, service)
    app.dependency_overrides[get_token_cipher] = lambda: cipher
    return TestClient(app, base_url=ORIGIN), service, cipher


def cookie(token: str) -> dict[str, str]:
    return {"Cookie": f"__Host-roombook_session={token}"}


def test_auth_disabled_is_safe_without_database_or_provider() -> None:
    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        response = client.get("/api/v1/auth/session")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"
        assert response.headers["Cache-Control"] == "private, no-store"
        assert client.get("/health").status_code == 200
        assert client.get("/version").status_code == 200


def test_session_response_has_only_local_user_and_safe_session_fields(
    http_identity: tuple[TestClient, StubSessions, TokenCipher],
) -> None:
    client, service, cipher = http_identity
    response = client.get("/api/v1/auth/session", headers=cookie(TOKEN_A))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"user", "aal", "purpose", "expires_at", "csrf_token"}
    assert body["purpose"] == "standard"
    assert body["user"] == {"id": str(service.results[TOKEN_A].user_id), "role": "Member"}
    assert body["csrf_token"] == cipher.csrf_token(TOKEN_A)
    assert TOKEN_A not in response.text
    assert "refresh_token" not in response.text
    assert "access_token" not in response.text
    assert "Set-Cookie" not in response.headers
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_two_users_and_logout_do_not_share_session_responses(
    http_identity: tuple[TestClient, StubSessions, TokenCipher],
) -> None:
    client, service, cipher = http_identity
    first = client.get("/api/v1/auth/session", headers=cookie(TOKEN_A))
    second = client.get("/api/v1/auth/session", headers=cookie(TOKEN_B))
    assert first.json()["user"] != second.json()["user"]
    result = client.post(
        "/api/v1/auth/logout",
        headers={**cookie(TOKEN_A), "Origin": ORIGIN, "X-CSRF-Token": cipher.csrf_token(TOKEN_A)},
    )
    assert result.status_code == 204
    assert client.get("/api/v1/auth/session", headers=cookie(TOKEN_A)).status_code == 401
    assert client.get("/api/v1/auth/session", headers=cookie(TOKEN_B)).status_code == 200
    assert service.revoked == [TOKEN_A]


@pytest.mark.parametrize("token", [None, "short", "c" * 43])
def test_missing_or_invalid_session_clears_cookie(
    http_identity: tuple[TestClient, StubSessions, TokenCipher], token: str | None
) -> None:
    client, _, _ = http_identity
    response = client.get("/api/v1/auth/session", headers=cookie(token) if token else {})
    assert response.status_code == 401
    assert "Max-Age=0" in response.headers["Set-Cookie"]
    assert "Secure" in response.headers["Set-Cookie"]
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("failure,status", [(InvalidIdentity(), 401), (ProviderUnavailable(), 503)])
def test_provider_failures_have_safe_private_responses(
    http_identity: tuple[TestClient, StubSessions, TokenCipher], failure: Exception, status: int
) -> None:
    client, service, _ = http_identity
    service.failure = failure
    response = client.get("/api/v1/auth/session", headers=cookie(TOKEN_A))
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "private, no-store"
    assert TOKEN_A not in response.text


def test_recovery_session_cannot_use_normal_account_endpoint(
    http_identity: tuple[TestClient, StubSessions, TokenCipher],
) -> None:
    from dataclasses import replace

    client, service, _ = http_identity
    service.results[TOKEN_A] = replace(service.results[TOKEN_A], purpose="recovery")
    response = client.get("/api/v1/auth/session", headers=cookie(TOKEN_A))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "RECOVERY_RESTRICTED"


@pytest.mark.parametrize("origin", [None, "https://evil.example", "null", ORIGIN + "/"])
def test_logout_rejects_missing_or_wrong_origin(
    http_identity: tuple[TestClient, StubSessions, TokenCipher], origin: str | None
) -> None:
    client, service, cipher = http_identity
    headers = {**cookie(TOKEN_A), "X-CSRF-Token": cipher.csrf_token(TOKEN_A)}
    if origin is not None:
        headers["Origin"] = origin
    response = client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 403
    assert service.revoked == []


@pytest.mark.parametrize("csrf", ["", "wrong", "x" * 100])
def test_logout_rejects_missing_or_wrong_csrf(
    http_identity: tuple[TestClient, StubSessions, TokenCipher], csrf: str
) -> None:
    client, service, _ = http_identity
    response = client.post(
        "/api/v1/auth/logout",
        headers={**cookie(TOKEN_A), "Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 403
    assert service.revoked == []


def test_logout_does_not_require_live_provider_and_is_idempotent(
    http_identity: tuple[TestClient, StubSessions, TokenCipher],
) -> None:
    client, service, cipher = http_identity
    service.failure = ProviderUnavailable()
    headers = {**cookie(TOKEN_A), "Origin": ORIGIN, "X-CSRF-Token": cipher.csrf_token(TOKEN_A)}
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 204


def test_cross_site_fetch_metadata_rejected_even_with_token(
    http_identity: tuple[TestClient, StubSessions, TokenCipher],
) -> None:
    client, _, cipher = http_identity
    response = client.post(
        "/api/v1/auth/logout",
        headers={
            **cookie(TOKEN_A),
            "Origin": ORIGIN,
            "Sec-Fetch-Site": "cross-site",
            "X-CSRF-Token": cipher.csrf_token(TOKEN_A),
        },
    )
    assert response.status_code == 403


def test_cookie_flags_and_development_cookie_name(
    http_identity: tuple[TestClient, StubSessions, TokenCipher],
) -> None:
    _, service, _ = http_identity
    settings = Settings(_env_file=None, auth_enabled=False)
    response = Response()
    set_session_cookie(response, settings, service.results[TOKEN_A])
    header = response.headers["Set-Cookie"]
    assert header.startswith("__Host-roombook_session=")
    assert all(flag in header for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"))
    assert "Domain=" not in header
    assert "Max-Age=43200" in header
    local = settings.model_copy(update={"auth_cookie_secure": False})
    response = Response()
    set_session_cookie(response, local, service.results[TOKEN_A])
    assert response.headers["Set-Cookie"].startswith("roombook_session=")
    assert "Secure" not in response.headers["Set-Cookie"]


@pytest.mark.parametrize("path", ["/api/v1/auth/missing", "/api/v1/auth/session"])
def test_auth_404_and_405_are_private(
    http_identity: tuple[TestClient, StubSessions, TokenCipher], path: str
) -> None:
    client, _, _ = http_identity
    response = client.put(path)
    assert response.status_code in {404, 405}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_unexpected_auth_exception_does_not_expose_credentials(
    http_identity: tuple[TestClient, StubSessions, TokenCipher], caplog: pytest.LogCaptureFixture
) -> None:
    client, service, _ = http_identity
    service.failure = RuntimeError("private-access-token private-refresh-token")
    # An exception must not escape to Uvicorn, which would log its full traceback.
    safe_client = TestClient(client.app, base_url=ORIGIN, raise_server_exceptions=True)
    with caplog.at_level(logging.WARNING):
        response = safe_client.get("/api/v1/auth/session", headers=cookie(TOKEN_A))
    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "private-access-token" not in response.text + caplog.text
    assert "private-refresh-token" not in response.text + caplog.text


def test_access_log_filter_redacts_account_query_and_path_credentials() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "test",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("client", "GET", "/api/v1/auth/secret?token_hash=one-time-secret", "1.1", 200),
        None,
    )
    assert IdentityAccessLogFilter().filter(record)
    assert "one-time-secret" not in record.getMessage()
    assert "/api/v1/auth/secret" not in record.getMessage()
