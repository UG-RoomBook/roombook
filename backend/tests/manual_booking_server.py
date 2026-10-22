"""Opt-in RB-16 loopback fixture: real sessions/bookings, synthetic identity.

Run from backend with ROOMBOOK_TEST_DATABASE_URL pointing to a localhost *_test
database: .venv/bin/python -m tests.manual_booking_server
The first booking receipt is replaced with 503 after commit for reconciliation.
This fixture never resets or deletes data. It is not part of the production app.
"""

import os
from unittest.mock import patch

import httpx
import uvicorn
from cryptography.fernet import Fernet
from fastapi import Request
from sqlalchemy.engine import make_url
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.main import create_app
from app.modules.identity.provider import SupabaseProvider
from scripts.seed_synthetic_calendar import seed_synthetic_calendar
from tests.identity.test_accounts import Harness


def main() -> None:
    url = os.environ["ROOMBOOK_TEST_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host not in {"localhost", "127.0.0.1", "::1"} or not (parsed.database or "").endswith(
        "_test"
    ):
        raise ValueError("Use a dedicated localhost database ending in _test")
    settings = Settings(
        _env_file=None,
        database_url=url,
        environment="test",
        auth_enabled=True,
        auth_supabase_url="https://identity.example",
        auth_site_url="http://127.0.0.1:5173",
        auth_supabase_publishable_key="synthetic-publishable-key",
        auth_token_encryption_key=Fernet.generate_key().decode(),
        commit_sha=os.environ.get("ROOMBOOK_COMMIT_SHA", "RB-16-working-tree"),
    )
    harness = Harness()
    with httpx.Client(transport=httpx.MockTransport(harness.transport)) as transport:
        provider = SupabaseProvider("https://identity.example", "synthetic-key", client=transport)
        with patch("app.main.SupabaseProvider", return_value=provider):
            app = create_app(settings)
        with app.state.database.session() as session, session.begin():
            seed_synthetic_calendar(session, settings)
        lost = False

        @app.middleware("http")
        async def lose_first_receipt(
            request: Request, call_next: RequestResponseEndpoint
        ) -> Response:
            nonlocal lost
            response = await call_next(request)
            if (
                request.method == "POST"
                and request.url.path == "/api/v1/bookings"
                and response.status_code == 201
                and not lost
            ):
                lost = True
                print("SYNTHETIC: first booking committed; receipt replaced with 503", flush=True)
                return JSONResponse(
                    {
                        "error": {
                            "code": "SERVICE_UNAVAILABLE",
                            "message": "Synthetic lost response after commit.",
                        }
                    },
                    status_code=503,
                    headers={"Cache-Control": "private, no-store"},
                )
            return response

        uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
