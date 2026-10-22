"""Opt-in loopback browser fixture; excluded from the application image.

Uses real routes, session persistence and booking transactions. Only the external
identity provider is synthetic. Requires a dedicated empty *_e2e_test database.
"""

import os
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import Response
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.frontend import install_frontend
from app.main import create_app
from app.modules.availability.models import WeeklyHours
from app.modules.availability.policy import current_time
from app.modules.bookings.models import Booking
from app.modules.bookings.service import create_booking
from app.modules.identity.router import set_session_cookie
from app.modules.rooms.models import Room
from scripts.seed_rooms import seed_rooms
from tests.identity.test_service import Harness, TrackingDatabase

URL = os.environ["ROOMBOOK_E2E_DATABASE_URL"]
url = make_url(URL)
if url.host not in {"localhost", "127.0.0.1", "::1"} or not (url.database or "").endswith(
    "_e2e_test"
):
    raise RuntimeError("Browser fixtures require a dedicated loopback *_e2e_test database")

NOW = datetime(2026, 10, 18, tzinfo=UTC)
engine = create_engine(URL)
with Session(engine) as db, db.begin():
    if db.scalar(select(func.count()).select_from(Room)):
        raise RuntimeError(
            "Browser fixture database must be empty; refusing to change existing data"
        )
    seed_rooms(db)
    for room in db.scalars(select(Room)):
        room.hours_confirmed = True
        db.add_all(
            WeeklyHours(room_id=room.id, weekday=day, start_minute=540, end_minute=1020)
            for day in range(7)
        )
        if room.name == "The Studio":
            db.add(
                Booking(
                    id=uuid4(),
                    room_id=room.id,
                    starts_at=datetime.fromisoformat("2026-10-19T10:45+11:00"),
                    ends_at=datetime.fromisoformat("2026-10-19T11:15+11:00"),
                    status="active",
                    created_at=NOW,
                )
            )

database = TrackingDatabase(URL)
harness = Harness(database, engine)
harness.clock.now = NOW
harness.provider.identity = harness.provider.identity.__class__(
    issuer="https://test-identity.invalid/auth/v1",
    subject=str(uuid4()),
    session_id=str(uuid4()),
    email="browser-fixture@example.invalid",
    email_verified=True,
    aal="aal1",
    expires_at=NOW + timedelta(hours=1),
)
settings = Settings(
    _env_file=None,
    database_url=URL,
    environment="test",
    auth_site_url="http://127.0.0.1:8011",
    auth_cookie_secure=False,
    static_dir=None,
)
app = create_app(settings)
app.state.identity_sessions = harness.service
app.state.identity_cipher = harness.cipher
app.dependency_overrides[current_time] = lambda: NOW
patch(
    "app.modules.bookings.router.create_booking", partial(create_booking, clock=lambda: NOW)
).start()


@app.post("/__fixture/session", include_in_schema=False)
def fixture_session() -> Response:
    token = harness.establish()
    response = Response(status_code=204)
    set_session_cookie(response, settings, harness.service.authenticate(token))
    return response


install_frontend(app, Path(__file__).resolve().parents[2] / "frontend" / "dist")
