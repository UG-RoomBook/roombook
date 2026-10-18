from fastapi import APIRouter, Request

from app.core.errors import ApiError, ErrorResponse
from app.modules.operations.schemas import (
    HealthResponse,
    ReadinessResponse,
    RuntimeVersion,
)

router = APIRouter(tags=["Operations"])


@router.get("/health", response_model=HealthResponse, operation_id="getHealth")
def health() -> HealthResponse:
    """Report process health without accessing PostgreSQL."""
    return HealthResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    operation_id="getReadiness",
    responses={503: {"model": ErrorResponse, "description": "PostgreSQL is unavailable"}},
)
def readiness(request: Request) -> ReadinessResponse:
    """Report readiness after a bounded PostgreSQL SELECT 1."""
    if not request.app.state.database.ready():
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The database is unavailable.")
    return ReadinessResponse()


@router.get("/version", response_model=RuntimeVersion, operation_id="getVersion")
def version(request: Request) -> RuntimeVersion:
    """Return the configured source identity and environment, without secrets."""
    settings = request.app.state.settings
    return RuntimeVersion(
        commit_sha=settings.commit_sha,
        environment=settings.environment,
        version=settings.version,
    )
