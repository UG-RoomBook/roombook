"""Loopback-only admin browser fixture with real PostgreSQL and a synthetic TOTP provider."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from fastapi import Request, Response
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.frontend import install_frontend
from app.main import create_app
from app.modules.availability.models import WeeklyHours
from app.modules.bookings.models import Booking
from app.modules.identity.accounts import AccountService
from app.modules.identity.dependencies import authenticated_session
from app.modules.identity.models import ApplicationUser, AuthSession
from app.modules.identity.provider import SupabaseProvider
from app.modules.identity.service import hash_token
from app.modules.rooms.models import Room
from scripts.seed_rooms import seed_rooms
from tests.admin_provider import AdminProvider

URL = os.environ["ROOMBOOK_E2E_DATABASE_URL"]
url = make_url(URL)
if url.host not in {"localhost", "127.0.0.1", "::1"} or not (url.database or "").endswith(
    "_e2e_test"
):
    raise RuntimeError("Admin fixtures require a dedicated loopback *_e2e_test database")
engine = create_engine(URL)
with Session(engine) as db, db.begin():
    if db.scalar(select(func.count()).select_from(Room)):
        raise RuntimeError("Admin fixture database must be empty; refusing to change existing data")
    seed_rooms(db)
    for room in db.scalars(select(Room)):
        room.hours_confirmed = True
        for day in range(7):
            db.add(WeeklyHours(room_id=room.id, weekday=day, start_minute=0, end_minute=1440))
        if room.name == "The Studio":
            now = datetime.now(UTC)
            db.add(
                Booking(
                    room_id=room.id,
                    starts_at=now - timedelta(minutes=15),
                    ends_at=now + timedelta(minutes=45),
                )
            )
harness = AdminProvider()
transport = httpx.Client(transport=httpx.MockTransport(harness.transport))
provider = SupabaseProvider("https://identity.example", "synthetic-key", client=transport)
settings = Settings(
    _env_file=None,
    database_url=URL,
    environment="test",
    auth_enabled=True,
    auth_supabase_url="https://identity.example",
    auth_site_url="http://127.0.0.1:8012",
    auth_cookie_secure=False,
    auth_supabase_publishable_key="synthetic-key",
    auth_token_encryption_key=Fernet.generate_key().decode(),
)
with patch("app.main.SupabaseProvider", return_value=provider):
    app = create_app(settings)
accounts = AccountService(app.state.identity_sessions, provider)
for email in ("admin@example.com", "colleague@example.com", "member@example.com"):
    result = accounts.login(email, "synthetic-password-123", None)
    with Session(engine) as db, db.begin():
        user = db.get(ApplicationUser, result.user_id)
        assert user is not None
        user.role = "Admin" if email != "member@example.com" else "Member"
    if email != "member@example.com":
        snapshot = accounts.sessions._read(hash_token(result.opaque_token))
        harness.factors[snapshot.subject] = [
            {
                "id": str(uuid4()),
                "friendly_name": "Test authenticator",
                "factor_type": "totp",
                "status": "verified",
            }
        ]


@app.post("/__fixture/age-mfa", include_in_schema=False)
def age_mfa(request: Request) -> Response:
    actor = authenticated_session(request, settings, accounts.sessions)
    with Session(engine) as db, db.begin():
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == actor.user_id)
            .values(mfa_verified_at=datetime.now(UTC) - timedelta(minutes=11))
        )
    return Response(status_code=204)


install_frontend(app, Path(__file__).resolve().parents[2] / "frontend" / "dist")
