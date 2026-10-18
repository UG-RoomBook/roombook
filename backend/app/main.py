from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings
from app.core.errors import ErrorResponse, install_error_handlers
from app.db.session import Database
from app.modules.operations.router import router as operations_router
from app.modules.rooms.router import router as rooms_router


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings if settings is not None else Settings()
    database = Database(configured.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
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
    install_error_handlers(application)
    application.include_router(operations_router)
    application.include_router(rooms_router)
    return application


app = create_app()
