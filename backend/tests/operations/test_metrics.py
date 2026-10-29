from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app import main
from app.core.config import Settings

SHA = "c" * 40


def samples(text: str, name: str) -> list[tuple[dict[str, str], float]]:
    return [
        (sample.labels, sample.value)
        for family in text_string_to_metric_families(text)
        for sample in family.samples
        if sample.name == name
    ]


@pytest.fixture
def application(tmp_path: Path) -> FastAPI:
    (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    return main.create_app(
        Settings(
            _env_file=None,
            database_url=None,
            environment="staging",
            commit_sha=SHA,
            static_dir=tmp_path,
        )
    )


def test_metrics_report_the_running_release(application: FastAPI) -> None:
    with TestClient(application) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert samples(response.text, "roombook_build_info") == [
        ({"commit_sha": SHA, "environment": "staging", "version": "0.2.1"}, 1.0)
    ]


def test_requests_are_labelled_by_route_template_and_status(application: FastAPI) -> None:
    with TestClient(application) as client:
        client.get("/health")
        client.get("/health")
        client.get("/api/v1/rooms")  # no database configured: 503
        client.get("/bookings/123")  # React fallback route
        text = client.get("/metrics").text

    counts = {
        (labels["route"], labels["status"]): value
        for labels, value in samples(text, "roombook_http_requests_total")
    }
    assert counts[("/health", "200")] == 2
    assert counts[("/api/v1/rooms", "503")] == 1
    assert counts[("/{path:path}", "200")] == 1
    # Concrete paths never become label values.
    assert not any("123" in route for route, _ in counts)


def test_unknown_routes_share_one_label(tmp_path: Path) -> None:
    app = main.create_app(
        Settings(_env_file=None, database_url=None, environment="test", commit_sha=SHA)
    )
    with TestClient(app) as client:
        assert client.get("/no/such/page").status_code == 404
        assert client.get("/another/missing/page").status_code == 404
        text = client.get("/metrics").text
    unmatched = [
        value
        for labels, value in samples(text, "roombook_http_requests_total")
        if labels["route"] == "unmatched"
    ]
    assert unmatched == [2.0]


def test_latency_histogram_has_the_target_bucket(application: FastAPI) -> None:
    with TestClient(application) as client:
        client.get("/health")
        text = client.get("/metrics").text
    buckets = {
        labels["le"]
        for labels, _ in samples(text, "roombook_http_request_duration_seconds_bucket")
        if labels["route"] == "/health"
    }
    assert "0.3" in buckets


def test_metrics_stay_out_of_the_public_api_schema(application: FastAPI) -> None:
    assert "/metrics" not in application.openapi()["paths"]
