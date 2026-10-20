"""Prometheus metrics for HTTP traffic and the running release.

`GET /metrics` serves the Prometheus text format. Prometheus on the Production
host scrapes it over the private Docker network; Caddy refuses `/metrics` on
the public site. Routes are labelled by their template (``/api/v1/rooms``,
``/{path:path}``), never by concrete IDs, so label values stay bounded.
"""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.responses import Response
from starlette.routing import Match

from app.core.config import Settings

# Seconds. Dense around the brief's 300 ms p95 target.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0)
UNMATCHED = "unmatched"


def route_template(request: Request) -> str:
    """The path template of the route that handles the request, or ``unmatched``."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path
    for candidate in request.app.router.routes:
        match, _ = candidate.matches(request.scope)
        if match is Match.FULL:
            template = getattr(candidate, "path", None)
            if isinstance(template, str):
                return template
    return UNMATCHED


def install_metrics(application: FastAPI, settings: Settings) -> None:
    # One registry per application instance keeps tests and reloads independent.
    registry = CollectorRegistry(auto_describe=True)
    requests = Counter(
        "roombook_http_requests_total",
        "HTTP requests by method, route template and status code.",
        ["method", "route", "status"],
        registry=registry,
    )
    duration = Histogram(
        "roombook_http_request_duration_seconds",
        "HTTP request duration by method and route template.",
        ["method", "route"],
        buckets=LATENCY_BUCKETS,
        registry=registry,
    )
    build = Gauge(
        "roombook_build_info",
        "The running release: always 1, labelled with its source commit.",
        ["commit_sha", "environment", "version"],
        registry=registry,
    )
    build.labels(settings.commit_sha, settings.environment, settings.version).set(1)
    application.state.metrics_registry = registry

    @application.middleware("http")
    async def measure(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = route_template(request)
            elapsed = time.perf_counter() - started
            requests.labels(request.method, route, str(status)).inc()
            duration.labels(request.method, route).observe(elapsed)

    @application.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
