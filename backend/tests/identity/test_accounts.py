"""Real HTTP, JWT and PostgreSQL account flows; outbound provider/mail is synthetic."""

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.modules.identity.accounts import AccountAttempt
from app.modules.identity.models import AuthSession
from app.modules.identity.provider import SupabaseProvider

ORIGIN = "https://roombook.example"
EMAIL = "member@example.com"
PASSWORD = "synthetic-password-123"
pytestmark = pytest.mark.database


class Harness:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.confirmed = True
        self.unavailable = False
        self.reject_send = False
        self.used: set[str] = set()
        self.subject = str(uuid4())
        now = datetime.now(UTC)
        key = ec.generate_private_key(ec.SECP256R1())
        self.signing_key = key
        self.other_tokens: dict[str, str] = {}
        self.jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
        self.jwk.update(kid="synthetic", alg="ES256", use="sig")
        self.access = jwt.encode(
            {
                "iss": "https://identity.example/auth/v1",
                "aud": "authenticated",
                "sub": self.subject,
                "session_id": str(uuid4()),
                "email": EMAIL,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(hours=1)).timestamp()),
                "role": "authenticated",
                "aal": "aal1",
                "is_anonymous": False,
            },
            key,
            algorithm="ES256",
            headers={"kid": "synthetic"},
        )

    def transport(self, request: httpx.Request) -> httpx.Response:
        payload: dict[str, str] = json.loads(request.content) if request.content else {}
        path = request.url.path.removeprefix("/auth/v1")
        self.calls.append((request.method, path, payload))
        if self.unavailable:
            return httpx.Response(503, json={"secret": "never-return-provider-payload"})
        if path == "/.well-known/jwks.json":
            return httpx.Response(200, json={"keys": [self.jwk]})
        if path == "/user":
            access = request.headers["authorization"].removeprefix("Bearer ")
            # Fixture lookup only; the application independently validates the real signature.
            claims = jwt.decode(access, options={"verify_signature": False})
            return httpx.Response(
                200,
                json={
                    "id": claims["sub"],
                    "email": claims["email"],
                    "aud": "authenticated",
                    "is_anonymous": False,
                    "email_confirmed_at": "2026-01-01T00:00:00Z" if self.confirmed else None,
                },
            )
        if path in {"/signup", "/recover", "/resend"}:
            return httpx.Response(400 if self.reject_send else 200, json={})
        if path == "/verify":
            token = payload["token_hash"]
            if token in self.used:
                return httpx.Response(400, json={"error_code": "otp_expired"})
            self.used.add(token)
        elif path != "/token":
            raise AssertionError(path)
        if payload.get("password") == "wrong-password":
            return httpx.Response(400, json={"error_code": "invalid_credentials"})
        access = self.access
        if path == "/token" and payload.get("email", EMAIL) != EMAIL:
            email = payload["email"]
            if email not in self.other_tokens:
                claims = jwt.decode(self.access, options={"verify_signature": False})
                claims.update(sub=str(uuid4()), session_id=str(uuid4()), email=email)
                self.other_tokens[email] = jwt.encode(
                    claims, self.signing_key, algorithm="ES256", headers={"kid": "synthetic"}
                )
            access = self.other_tokens[email]
        return httpx.Response(
            200,
            json={
                "access_token": access,
                "refresh_token": "synthetic-refresh-secret",
                "token_type": "bearer",
            },
        )


@pytest.fixture
def accounts(database_url: str, clean_database: None) -> Iterator[tuple[TestClient, Harness]]:
    harness = Harness()
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        environment="test",
        auth_enabled=True,
        auth_supabase_url="https://identity.example",
        auth_site_url=ORIGIN,
        auth_supabase_publishable_key="synthetic-publishable-key",
        auth_token_encryption_key=Fernet.generate_key().decode(),
    )
    with httpx.Client(transport=httpx.MockTransport(harness.transport)) as transport:
        provider = SupabaseProvider("https://identity.example", "synthetic-key", client=transport)
        with patch("app.main.SupabaseProvider", return_value=provider):
            app = create_app(settings)
        with TestClient(app, base_url=ORIGIN) as client:
            yield client, harness


def login(client: TestClient) -> httpx.Response:
    return cast(
        httpx.Response,
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": EMAIL, "password": PASSWORD},
        ),
    )


def open_link(client: TestClient, kind: str, token: str = "a" * 64) -> dict[str, str]:
    response = client.get("/api/v1/auth/confirm", params={"token_hash": token, "type": kind})
    assert response.status_code == 200
    csrf = re.search(r'name="csrf" value="([a-f0-9]+)"', response.text)
    assert csrf is not None
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "script-src 'nonce-" in response.headers["Content-Security-Policy"]
    assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
    # A native form POST under no-referrer sends Origin:null in real browsers.
    # CORS-mode fetch preserves Origin without exposing the email-link URL.
    assert "mode:'cors',referrerPolicy:'no-referrer'" in response.text
    assert "location.replace(target.href)" in response.text
    assert 'type="submit" disabled' in response.text
    return {"token_hash": token, "type": kind, "csrf": csrf.group(1)}


@pytest.mark.parametrize("action", ["register", "recover", "resend"])
def test_send_is_generic_and_never_issues_a_session(
    accounts: tuple[TestClient, Harness], action: str
) -> None:
    client, provider = accounts
    body = {"email": EMAIL, **({"password": PASSWORD} if action == "register" else {})}
    first = client.post(f"/api/v1/auth/{action}", headers={"Origin": ORIGIN}, json=body)
    provider.reject_send = True
    second = client.post(f"/api/v1/auth/{action}", headers={"Origin": ORIGIN}, json=body)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert "set-cookie" not in first.headers
    assert provider.access not in first.text


def test_verified_login_issues_only_secure_opaque_cookie(
    accounts: tuple[TestClient, Harness],
) -> None:
    client, provider = accounts
    response = login(client)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "Member"
    cookie = response.headers["set-cookie"]
    assert all(
        value in cookie
        for value in ["__Host-roombook_session=", "HttpOnly", "Secure", "SameSite=lax"]
    )
    assert provider.access not in response.text + cookie
    assert "synthetic-refresh-secret" not in response.text + cookie
    assert client.get("/api/v1/auth/session").status_code == 200


def test_unverified_and_wrong_password_cannot_login(accounts: tuple[TestClient, Harness]) -> None:
    client, provider = accounts
    provider.confirmed = False
    assert login(client).status_code == 401
    provider.confirmed = True
    assert (
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": EMAIL, "password": "wrong-password"},
        ).status_code
        == 401
    )


@pytest.mark.parametrize("action", ["login", "register", "recover", "resend"])
@pytest.mark.parametrize("origin", [None, "https://attacker.example", "null"])
def test_public_mutations_require_own_origin(
    accounts: tuple[TestClient, Harness], action: str, origin: str | None
) -> None:
    client, provider = accounts
    response = client.post(
        f"/api/v1/auth/{action}",
        headers={"Origin": origin} if origin else {},
        json={
            "email": EMAIL,
            **({"password": PASSWORD} if action in {"login", "register"} else {}),
        },
    )
    assert response.status_code == 403
    assert not provider.calls


def test_scanners_do_not_consume_links_and_replay_is_rejected(
    accounts: tuple[TestClient, Harness],
) -> None:
    client, provider = accounts
    body = open_link(client, "email")
    assert not provider.calls
    response = client.post(
        "/api/v1/auth/confirm", headers={"Origin": ORIGIN}, data=body, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/account/login?notice=verified"
    assert client.get("/api/v1/auth/session").status_code == 401
    body = open_link(client, "email")
    response = client.post(
        "/api/v1/auth/confirm", headers={"Origin": ORIGIN}, data=body, follow_redirects=False
    )
    assert response.headers["location"] == "/account/login?notice=link-error"


def test_callback_keeps_strict_origin_validation_with_valid_cookie_and_csrf(
    accounts: tuple[TestClient, Harness],
) -> None:
    client, provider = accounts
    body = open_link(client, "email")
    for headers in [{}, {"Origin": "null"}, {"Origin": "https://attacker.example"}]:
        response = client.post("/api/v1/auth/confirm", headers=headers, data=body)
        assert response.status_code == 403
    assert not provider.calls
    response = client.post(
        "/api/v1/auth/confirm", headers={"Origin": ORIGIN}, data=body, follow_redirects=False
    )
    assert response.headers["location"] == "/account/login?notice=verified"


def test_recovery_is_restricted_then_revokes_all_sessions(
    accounts: tuple[TestClient, Harness], db_engine: Engine
) -> None:
    client, _ = accounts
    assert login(client).status_code == 200
    body = open_link(client, "recovery")
    assert (
        client.post(
            "/api/v1/auth/confirm", headers={"Origin": ORIGIN}, data=body, follow_redirects=False
        ).headers["location"]
        == "/account/reset"
    )
    assert client.get("/api/v1/auth/session").status_code == 403
    recovery = client.get("/api/v1/auth/recovery-session")
    assert recovery.status_code == 200
    assert (
        client.post(
            "/api/v1/auth/reset-password", headers={"Origin": ORIGIN}, json={"password": PASSWORD}
        ).status_code
        == 403
    )
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"password": PASSWORD},
        headers={"Origin": ORIGIN, "X-CSRF-Token": recovery.json()["csrf_token"]},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/auth/recovery-session").status_code == 401
    with Session(db_engine) as db:
        assert all(s.revoked_at is not None for s in db.scalars(select(AuthSession)).all())


def test_standard_session_cannot_reset_password(accounts: tuple[TestClient, Harness]) -> None:
    client, _ = accounts
    session = login(client).json()
    assert client.get("/api/v1/auth/recovery-session").status_code == 403
    assert (
        client.post(
            "/api/v1/auth/reset-password",
            json={"password": PASSWORD},
            headers={"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]},
        ).status_code
        == 403
    )


def test_email_change_requires_csrf_and_ends_local_session(
    accounts: tuple[TestClient, Harness],
) -> None:
    client, _ = accounts
    session = login(client).json()
    assert (
        client.post(
            "/api/v1/auth/change-email",
            headers={"Origin": ORIGIN},
            json={"email": "new@example.com"},
        ).status_code
        == 403
    )
    response = client.post(
        "/api/v1/auth/change-email",
        json={"email": "new@example.com"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 401


def test_rate_limit_survives_across_service_instances_and_stores_no_email(
    accounts: tuple[TestClient, Harness], db_engine: Engine
) -> None:
    client, _ = accounts
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/auth/recover", headers={"Origin": ORIGIN}, json={"email": EMAIL}
            ).status_code
            == 200
        )
    assert (
        client.post(
            "/api/v1/auth/recover", headers={"Origin": ORIGIN}, json={"email": EMAIL}
        ).status_code
        == 429
    )
    with Session(db_engine) as db:
        assert all(re.fullmatch(r"[a-f0-9]{64}", a.key) for a in db.scalars(select(AccountAttempt)))


def test_outage_and_validation_do_not_leak_submitted_secrets(
    accounts: tuple[TestClient, Harness],
) -> None:
    client, provider = accounts
    provider.unavailable = True
    response = login(client)
    assert response.status_code == 503
    assert PASSWORD not in response.text and "never-return-provider-payload" not in response.text
    response = client.post(
        "/api/v1/auth/register",
        headers={"Origin": ORIGIN},
        json={"email": EMAIL, "password": "short-secret", "role": "Admin"},
    )
    assert response.status_code == 422 and "short-secret" not in response.text


def test_separate_browser_logins_keep_distinct_users_and_logout_boundaries(
    accounts: tuple[TestClient, Harness],
) -> None:
    client, _ = accounts
    first = login(client).json()
    first_cookie = client.cookies.get("__Host-roombook_session")
    client.cookies.clear()
    second_response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "second@example.com", "password": PASSWORD},
    )
    assert second_response.status_code == 200
    second = second_response.json()
    second_cookie = client.cookies.get("__Host-roombook_session")
    assert first["user"]["id"] != second["user"]["id"]
    assert first_cookie != second_cookie
    first_headers = {"Cookie": f"__Host-roombook_session={first_cookie}"}
    second_headers = {"Cookie": f"__Host-roombook_session={second_cookie}"}
    assert client.get("/api/v1/auth/session", headers=first_headers).json()["user"] == first["user"]
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={**first_headers, "Origin": ORIGIN, "X-CSRF-Token": first["csrf_token"]},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/session", headers=first_headers).status_code == 401
    assert (
        client.get("/api/v1/auth/session", headers=second_headers).json()["user"] == second["user"]
    )


def test_confirmation_rejects_tampered_csrf_and_disallowed_link_types(
    accounts: tuple[TestClient, Harness],
) -> None:
    client, provider = accounts
    body = open_link(client, "email")
    body["csrf"] = "tampered"
    assert (
        client.post("/api/v1/auth/confirm", headers={"Origin": ORIGIN}, data=body).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/auth/confirm", params={"token_hash": "a" * 64, "type": "magiclink"}
        ).status_code
        == 422
    )
    assert not provider.calls


def test_email_change_confirmation_never_grants_a_session(
    accounts: tuple[TestClient, Harness],
) -> None:
    client, _ = accounts
    body = open_link(client, "email_change")
    response = client.post(
        "/api/v1/auth/confirm",
        headers={"Origin": ORIGIN},
        data=body,
        follow_redirects=False,
    )
    assert response.headers["location"] == "/account/login?notice=email-change"
    assert "__Host-roombook_session=" not in response.headers.get("set-cookie", "")
