from collections.abc import Iterator
from typing import cast
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.modules.identity.models import ApplicationUser
from app.modules.identity.provider import SupabaseProvider
from tests.admin_provider import CODE, AdminProvider
from tests.identity.test_accounts import ORIGIN, login


@pytest.fixture
def mfa_account(
    database_url: str, clean_database: None
) -> Iterator[tuple[TestClient, AdminProvider]]:
    harness = AdminProvider()
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


def headers(client: TestClient, key: str | None = None) -> dict[str, str]:
    result = client.get("/api/v1/auth/session")
    assert result.status_code == 200, result.text
    return {
        "Origin": ORIGIN,
        "X-CSRF-Token": result.json()["csrf_token"],
        **({"Idempotency-Key": key} if key else {}),
    }


def complete_mfa(client: TestClient) -> httpx.Response:
    response = client.post(
        "/api/v1/auth/mfa/enroll", json={"name": "Test authenticator"}, headers=headers(client)
    )
    assert response.status_code == 200, response.text
    result = client.post(
        "/api/v1/auth/mfa/verify",
        json={"factor_id": response.json()["id"], "code": CODE},
        headers=headers(client),
    )
    assert result.status_code == 200, result.text
    return cast(httpx.Response, result)


@pytest.fixture
def admin(
    mfa_account: tuple[TestClient, AdminProvider], db_engine: Engine
) -> tuple[TestClient, AdminProvider]:
    client, _ = mfa_account
    user_id = UUID(login(client).json()["user"]["id"])
    with Session(db_engine) as db, db.begin():
        user = db.get(ApplicationUser, user_id)
        assert user is not None
        user.role = "Admin"
    complete_mfa(client)
    return mfa_account
