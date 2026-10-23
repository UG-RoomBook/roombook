from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.modules.identity.models import ApplicationUser, AuditEvent, AuthSession
from app.modules.identity.service import InvalidSession, hash_token
from app.modules.identity.types import ProviderTokens
from scripts.bootstrap_admin import bootstrap
from tests.admin.conftest import complete_mfa, headers
from tests.admin_provider import CODE, AdminProvider
from tests.identity.test_accounts import login

pytestmark = pytest.mark.database


def test_enrollment_verification_rotation_and_last_factor_guard(
    admin: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, provider = admin
    session = client.get("/api/v1/auth/session").json()
    assert session["aal"] == "aal2" and session["mfa_verified_at"]
    factor = client.get("/api/v1/auth/mfa").json()["factors"][0]
    response = client.post(
        f"/api/v1/auth/mfa/{factor['id']}/remove",
        json={"reason": "Replace phone"},
        headers=headers(client),
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "LAST_ADMIN_FACTOR"
    old = client.cookies.get("__Host-roombook_session")
    new = complete_mfa(client)
    assert old != client.cookies.get("__Host-roombook_session")
    assert "SYNTHETIC" not in new.text and "access_token" not in new.text
    response = client.post(
        f"/api/v1/auth/mfa/{factor['id']}/remove",
        json={"reason": "Replace phone"},
        headers=headers(client),
    )
    assert response.status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 401
    with Session(db_engine) as db:
        assert all(s.revoked_at for s in db.scalars(select(AuthSession)))
        assert "SYNTHETICTOTPKEY" not in str([e.details for e in db.scalars(select(AuditEvent))])
    assert len(provider.factors[provider.subject]) == 1


def test_wrong_code_csrf_and_unknown_factor(mfa_account: tuple[TestClient, AdminProvider]) -> None:
    client, provider = mfa_account
    login(client)
    assert client.post("/api/v1/auth/mfa/enroll", json={"name": "Phone"}).status_code == 403
    enrolled = client.post(
        "/api/v1/auth/mfa/enroll", json={"name": "Phone"}, headers=headers(client)
    )
    assert enrolled.status_code == 200
    factor = enrolled.json()["id"]
    assert (
        client.post(
            "/api/v1/auth/mfa/verify",
            json={"factor_id": str(uuid4()), "code": CODE},
            headers=headers(client),
        ).status_code
        == 400
    )
    response = client.post(
        "/api/v1/auth/mfa/verify",
        json={"factor_id": factor, "code": "000000"},
        headers=headers(client),
    )
    assert response.status_code == 400
    assert client.get("/api/v1/auth/session").json()["aal"] == "aal1"
    provider.unavailable = True
    assert client.get("/api/v1/auth/mfa").status_code == 503


def test_uncertain_factor_removal_revokes_sessions(
    mfa_account: tuple[TestClient, AdminProvider],
) -> None:
    client, provider = mfa_account
    login(client)
    complete_mfa(client)
    factor = client.get("/api/v1/auth/mfa").json()["factors"][0]
    provider.fail_remove = True
    response = client.post(
        f"/api/v1/auth/mfa/{factor['id']}/remove",
        json={"reason": "Lost phone"},
        headers=headers(client),
    )
    assert response.status_code == 503
    assert client.get("/api/v1/auth/session").status_code == 401


def test_recent_timestamp_not_extended_by_refresh(
    admin: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, _ = admin
    before = client.get("/api/v1/auth/session").json()["mfa_verified_at"]
    service = client.app.state.identity_sessions  # type: ignore[attr-defined]
    service.policy = replace(service.policy, refresh_margin_seconds=3600)
    response = client.get("/api/v1/auth/session")
    assert response.status_code == 200 and response.json()["mfa_verified_at"] == before


def test_revoked_session_cannot_be_resurrected_by_mfa(
    mfa_account: tuple[TestClient, AdminProvider], db_engine: Engine
) -> None:
    client, provider = mfa_account
    login(client)
    result = complete_mfa(client)
    service = client.app.state.identity_sessions  # type: ignore[attr-defined]
    opaque = client.cookies.get("__Host-roombook_session")
    snapshot = service._read(hash_token(opaque))
    tokens = ProviderTokens(
        service.cipher.decrypt(snapshot.access_token_ciphertext),
        service.cipher.decrypt(snapshot.refresh_token_ciphertext),
    )
    with Session(db_engine) as db, db.begin():
        db.execute(update(AuthSession).values(revoked_at=datetime.now(UTC)))
    with pytest.raises(InvalidSession):
        service.establish(tokens, previous_token=opaque, mfa_user=UUID(result.json()["user"]["id"]))


def test_first_admin_requires_recent_mfa_and_revokes_old_session(
    mfa_account: tuple[TestClient, AdminProvider],
) -> None:
    client, provider = mfa_account
    login(client)
    service = client.app.state.identity_sessions  # type: ignore[attr-defined]

    def run() -> UUID:
        return bootstrap(
            service.database,
            environment="test",
            issuer="https://identity.example/auth/v1",
            subject=UUID(provider.subject),
            operator="test-operator",
            reason="Initial setup",
            idle_seconds=60,
        )

    with pytest.raises(ValueError, match="Complete MFA"):
        run()
    complete_mfa(client)
    with service.database.session() as db, db.begin():
        db.execute(
            update(AuthSession).values(last_seen_at=datetime.now(UTC) - timedelta(minutes=2))
        )
    with pytest.raises(ValueError, match="Complete MFA"):
        run()
    with service.database.session() as db, db.begin():
        db.execute(update(AuthSession).values(last_seen_at=datetime.now(UTC)))
    user_id = run()
    assert client.get("/api/v1/auth/session").status_code == 401
    with service.database.session() as db:
        assert db.get(ApplicationUser, user_id).role == "Admin"
    with pytest.raises(ValueError, match="already exists"):
        run()
