from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings
from app.core.errors import ErrorResponse, install_error_handlers
from app.core.frontend import install_frontend
from app.core.metrics import install_metrics
from app.db.session import Database
from app.modules.bookings.router import router as bookings_router
from app.modules.identity.account_router import router as account_router
from app.modules.identity.crypto import TokenCipher
from app.modules.identity.provider import SupabaseProvider
from app.modules.identity.router import router as identity_router
from app.modules.identity.security import install_identity_http_policy
from app.modules.identity.service import SessionPolicy, SessionService
from app.modules.operations.router import router as operations_router
from app.modules.rooms.router import router as rooms_router


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings if settings is not None else Settings()
    database = Database(configured.database_url)
    provider: SupabaseProvider | None = None
    cipher: TokenCipher | None = None
    identity_sessions: SessionService | None = None
    if configured.auth_enabled:
        assert configured.auth_supabase_url is not None
        assert configured.auth_supabase_publishable_key is not None
        assert configured.auth_token_encryption_key is not None
        provider = SupabaseProvider(
            configured.auth_supabase_url,
            configured.auth_supabase_publishable_key.get_secret_value(),
        )
        cipher = TokenCipher(configured.auth_token_encryption_key.get_secret_value())
        identity_sessions = SessionService(
            database,
            provider,
            cipher,
            SessionPolicy(
                idle_seconds=configured.auth_idle_seconds,
                absolute_seconds=configured.auth_absolute_seconds,
                revalidate_seconds=configured.auth_revalidate_seconds,
            ),
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if provider is not None:
                provider.close()
            database.dispose()

    application = FastAPI(
        title="RoomBook API",
        version=configured.version,
        description="Room discovery and booking service.",
        debug=False,
        lifespan=lifespan,
        responses={500: {"model": ErrorResponse, "description": "Unexpected error"}},
    )
    application.state.settings = configured
    application.state.database = database
    application.state.identity_sessions = identity_sessions
    application.state.identity_provider = provider
    application.state.identity_cipher = cipher
    install_error_handlers(application)
    install_identity_http_policy(application)
    install_metrics(application, configured)
    application.include_router(operations_router)
    application.include_router(rooms_router)
    application.include_router(identity_router)
    application.include_router(account_router)
    application.include_router(bookings_router)
    # Must stay last: the React fallback only handles paths no API route matched.
    install_frontend(application, configured.static_dir)
    return application


app = create_app()
