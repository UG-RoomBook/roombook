"""Public error responses and request correlation."""

import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException
from starlette.responses import Response

from app.db.session import DatabaseUnavailable

logger = logging.getLogger(__name__)


class ValidationDetail(BaseModel):
    field: str
    code: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: UUID
    details: list[ValidationDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    """An application failure whose message is safe to return to a caller."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Sequence[ValidationDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = list(details) if details is not None else None


def _request_id(request: Request) -> UUID:
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, UUID):
        request_id = uuid4()
        request.state.request_id = request_id
    return request_id


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[ValidationDetail] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            request_id=request_id,
            details=details,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", exclude_none=True),
        headers={**(headers or {}), "X-Request-ID": str(request_id)},
    )


def _validation_detail(error: dict[str, Any]) -> ValidationDetail:
    # Pydantic's input and context can contain submitted values or exception text.
    # Only return the field, error type and a fixed public message.
    parts = []
    for part in error.get("loc", ()):
        if isinstance(part, int):
            parts.append(str(part))
        elif isinstance(part, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part):
            parts.append(part)
        else:
            parts.append("[item]")
    code = str(error.get("type", "invalid"))
    messages = {
        "missing": "This field is required.",
        "int_parsing": "Enter a whole number.",
        "int_type": "Enter a whole number.",
        "uuid_parsing": "Enter a valid UUID.",
        "datetime_from_date_parsing": "Enter a valid timestamp with an offset.",
        "datetime_parsing": "Enter a valid timestamp with an offset.",
        "timezone_aware": "Include a timezone offset.",
        "greater_than_equal": "The value is below the allowed minimum.",
        "less_than_equal": "The value exceeds the allowed maximum.",
        "extra_forbidden": "This field is not supported.",
        "json_invalid": "Enter valid JSON.",
    }
    return ValidationDetail(
        field=".".join(parts), code=code, message=messages.get(code, "Invalid value.")
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlate_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        try:
            request.state.request_id = UUID(supplied)
        except ValueError:
            request.state.request_id = uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(_request_id(request))
        return response

    @app.exception_handler(ApiError)
    async def application_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            request,
            422,
            "VALIDATION_ERROR",
            "Check the request fields.",
            [_validation_detail(error) for error in exc.errors()],
        )

    @app.exception_handler(DatabaseUnavailable)
    @app.exception_handler(OperationalError)
    @app.exception_handler(PoolTimeoutError)
    async def database_unavailable(
        request: Request, _exc: DatabaseUnavailable | OperationalError | PoolTimeoutError
    ) -> JSONResponse:
        logger.warning("Database unavailable; request_id=%s", _request_id(request))
        return error_response(request, 503, "DATABASE_UNAVAILABLE", "The database is unavailable.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        messages = {
            400: ("BAD_REQUEST", "The request could not be processed."),
            404: ("NOT_FOUND", "The requested resource was not found."),
            405: ("METHOD_NOT_ALLOWED", "This method is not supported."),
        }
        code, message = messages.get(
            exc.status_code, ("HTTP_ERROR", "The request could not be processed.")
        )
        return error_response(request, exc.status_code, code, message, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Do not include exception messages, SQL statements or connection strings.
        logger.error("Unhandled %s; request_id=%s", type(exc).__name__, _request_id(request))
        return error_response(request, 500, "INTERNAL_ERROR", "An unexpected error occurred.")
