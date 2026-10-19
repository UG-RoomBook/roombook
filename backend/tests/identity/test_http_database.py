"""HTTP/session/PostgreSQL integration with locally signed, synthetic provider responses."""

import json
from datetime import UTC, datetime, timedelta
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
from app.modules.identity.models import ApplicationUser, AuthSession
from app.modules.identity.provider import SupabaseProvider
from app.modules.identity.service import SessionService, hash_token
from app.modules.identity.types import ProviderTokens

pytestmark = pytest.mark.database
ORIGIN = "https://roombook.example"
PROVIDER = "https://identity.example"


def test_signed_identity_to_cookie_session_and_local_logout(
    database_url: str,
    db_engine: Engine,
    clean_database: None,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    subject, session_id = str(uuid4()), str(uuid4())
    signing_key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(signing_key.public_key()))
    jwk.update({"kid": "local-test-key", "alg": "ES256", "use": "sig"})
    access_token = jwt.encode(
        {
            "iss": PROVIDER + "/auth/v1",
            "aud": "authenticated",
            "sub": subject,
            "session_id": session_id,
            "email": "synthetic@example.invalid",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "role": "authenticated",
            "aal": "aal1",
            "is_anonymous": False,
            "user_metadata": {"role": "Admin", "email_verified": True},
        },
        signing_key,
        algorithm="ES256",
        headers={"kid": "local-test-key"},
    )
    provider_paths: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        provider_paths.append(request.url.path)
        if request.url.path == "/auth/v1/.well-known/jwks.json":
            return httpx.Response(200, json={"keys": [jwk]})
        if request.url.path == "/auth/v1/user":
            assert request.headers["Authorization"] == "Bearer " + access_token
            return httpx.Response(
                200,
                json={
                    "id": subject,
                    "email": "synthetic@example.invalid",
                    "aud": "authenticated",
                    "is_anonymous": False,
                    "email_confirmed_at": now.isoformat(),
                },
            )
        raise AssertionError("Unexpected synthetic provider request")

    settings = Settings(
        _env_file=None,
        database_url=database_url,
        environment="test",
        auth_enabled=True,
        auth_supabase_url=PROVIDER,
        auth_site_url=ORIGIN,
        auth_supabase_publishable_key="synthetic-publishable-key",
        auth_token_encryption_key=Fernet.generate_key().decode(),
    )
    with httpx.Client(transport=httpx.MockTransport(transport)) as provider_http:
        provider = SupabaseProvider(PROVIDER, "synthetic-publishable-key", client=provider_http)
        with patch("app.main.SupabaseProvider", return_value=provider):
            app = create_app(settings)
        with TestClient(app, base_url=ORIGIN) as client:
            service: SessionService = app.state.identity_sessions
            result = service.establish(ProviderTokens(access_token, "synthetic-refresh-token"))
            headers = {"Cookie": f"__Host-roombook_session={result.opaque_token}"}
            response = client.get("/api/v1/auth/session", headers=headers)
            assert response.status_code == 200
            assert response.json()["user"] == {"id": str(result.user_id), "role": "Member"}
            assert response.json()["purpose"] == "standard"
            assert response.headers["Cache-Control"] == "private, no-store"
            assert access_token not in response.text
            with Session(db_engine) as db:
                record = db.scalar(
                    select(AuthSession).where(
                        AuthSession.token_hash == hash_token(result.opaque_token)
                    )
                )
                assert record is not None
                assert record.access_token_ciphertext != access_token
                assert record.refresh_token_ciphertext != "synthetic-refresh-token"
                assert record.revoked_at is None
            assert (
                client.post(
                    "/api/v1/auth/logout", headers={**headers, "Origin": ORIGIN}
                ).status_code
                == 403
            )
            assert client.get("/api/v1/auth/session", headers=headers).status_code == 200
            logout = client.post(
                "/api/v1/auth/logout",
                headers={
                    **headers,
                    "Origin": ORIGIN,
                    "X-CSRF-Token": response.json()["csrf_token"],
                },
            )
            assert logout.status_code == 204
            assert "Max-Age=0" in logout.headers["Set-Cookie"]
            assert client.get("/api/v1/auth/session", headers=headers).status_code == 401
            assert client.get("/api/v1/rooms").status_code == 200
            assert client.get("/health").status_code == 200
            assert client.get("/version").status_code == 200
            assert provider_paths == ["/auth/v1/.well-known/jwks.json", "/auth/v1/user"]
            with Session(db_engine) as db:
                user = db.get(ApplicationUser, result.user_id)
                assert user is not None and user.role == "Member"
