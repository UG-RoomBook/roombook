"""HTTP privacy headers and access-log redaction for account requests."""

import logging
from collections.abc import Awaitable, Callable
from urllib.parse import unquote

from fastapi import FastAPI, Request
from starlette.responses import Response

from app.core.errors import error_response

logger = logging.getLogger(__name__)


def is_identity_path(path: str) -> bool:
    decoded = unquote(path.split("?", 1)[0])
    return decoded == "/api/v1/auth" or decoded.startswith("/api/v1/auth/")


def apply_private_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


class IdentityAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn's access log arguments are (client, method, target, version, status).
        # Account paths and query strings may contain one-time credentials later.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            target = record.args[2]
            if isinstance(target, str) and is_identity_path(target):
                record.args = (*record.args[:2], "/api/v1/auth/[redacted]", *record.args[3:])
        return True


def install_identity_http_policy(app: FastAPI) -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, IdentityAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(IdentityAccessLogFilter())

    @app.middleware("http")
    async def private_responses(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            response = await call_next(request)
        except Exception as exc:
            if not is_identity_path(request.url.path):
                raise
            # ServerErrorMiddleware rethrows errors to Uvicorn, whose traceback can
            # reveal provider payloads. Consume account failures before that boundary.
            logger.error(
                "Unhandled account %s; request_id=%s",
                type(exc).__name__,
                getattr(request.state, "request_id", "unassigned"),
            )
            response = error_response(
                request, 500, "INTERNAL_ERROR", "An unexpected error occurred."
            )
        if is_identity_path(request.url.path) or "set-cookie" in response.headers:
            apply_private_headers(response)
        return response
