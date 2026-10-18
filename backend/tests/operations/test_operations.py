from typing import NoReturn
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app import main
from app.core.config import Settings
from app.core.errors import ApiError, ValidationDetail
from app.db.session import DatabaseUnavailable


class FakeDatabase:
    def __init__(self, url: str | None) -> None:
        self.url = url
        self.ready_result = True
        self.ready_calls = 0
        self.disposed = False

    def ready(self) -> bool:
        self.ready_calls += 1
        return self.ready_result

    def dispose(self) -> None:
        self.disposed = True


@pytest.fixture
def application(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(main, "Database", FakeDatabase)
    return main.create_app(
        Settings(
            _env_file=None,
            database_url=None,
            environment="test",
            commit_sha="a" * 40,
            version="0.1.0",
        )
    )


def test_health_does_not_query_database(application: FastAPI) -> None:
    application.state.database.ready_result = False
    with TestClient(application) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    assert application.state.database.ready_calls == 0


def test_readiness_requires_database_probe(application: FastAPI) -> None:
    with TestClient(application) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert application.state.database.ready_calls == 1


def test_readiness_failure_is_structured_and_correlated(application: FastAPI) -> None:
    application.state.database.ready_result = False
    with TestClient(application) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    UUID(response.headers["X-Request-ID"])


def test_runtime_identity_uses_only_configured_public_values(application: FastAPI) -> None:
    with TestClient(application) as client:
        response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {
        "commit_sha": "a" * 40,
        "environment": "test",
        "version": "0.1.0",
    }
    assert "database" not in response.text
    assert application.state.database.ready_calls == 0


def test_default_runtime_identity_does_not_invent_a_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ROOMBOOK_COMMIT_SHA", "ROOMBOOK_ENVIRONMENT", "ROOMBOOK_VERSION"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(main.create_app(Settings(_env_file=None, database_url=None))) as client:
        response = client.get("/version")
    assert response.json()["commit_sha"] == "unknown"


def test_database_is_disposed_at_shutdown(application: FastAPI) -> None:
    database = application.state.database
    assert not database.disposed
    with TestClient(application):
        assert not database.disposed
    assert database.disposed


def test_valid_request_id_is_preserved(application: FastAPI) -> None:
    supplied = str(uuid4())
    with TestClient(application) as client:
        response = client.get("/health", headers={"X-Request-ID": supplied})
    assert response.headers["X-Request-ID"] == supplied


def test_invalid_request_id_is_replaced(application: FastAPI) -> None:
    with TestClient(application) as client:
        response = client.get("/health", headers={"X-Request-ID": "untrusted-value"})
    UUID(response.headers["X-Request-ID"])
    assert response.headers["X-Request-ID"] != "untrusted-value"


@pytest.mark.parametrize("path", ["/api/missing", "/api/v1/missing", "/missing"])
def test_unknown_paths_return_json_instead_of_spa(application: FastAPI, path: str) -> None:
    with TestClient(application) as client:
        response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_method_error_keeps_allow_header(application: FastAPI) -> None:
    with TestClient(application) as client:
        response = client.post("/health")
    assert response.status_code == 405
    assert "GET" in response.headers["allow"]
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_application_errors_keep_safe_field_details(application: FastAPI) -> None:
    @application.get("/controlled-error", response_model=None)
    def controlled_error() -> NoReturn:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Choose an end after the start.",
            [ValidationDetail(field="query.ends_at", code="interval", message="Invalid interval.")],
        )

    with TestClient(application) as client:
        response = client.get("/controlled-error")
    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"field": "query.ends_at", "code": "interval", "message": "Invalid interval."}
    ]


def test_validation_never_echoes_submitted_values(application: FastAPI) -> None:
    class Body(BaseModel):
        secret: str = Field(min_length=30)

    @application.post("/validated")
    def validated(body: Body) -> dict[str, bool]:
        return {"accepted": bool(body.secret)}

    with TestClient(application) as client:
        response = client.post("/validated", json={"secret": "do-not-echo-this"})
    assert response.status_code == 422
    assert "do-not-echo-this" not in response.text
    assert response.json()["error"]["details"] == [
        {"field": "body.secret", "code": "string_too_short", "message": "Invalid value."}
    ]


def test_database_exception_does_not_expose_connection_details(
    application: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "postgresql://name:secret@private-host/roombook"

    @application.get("/database-error", response_model=None)
    def database_error() -> NoReturn:
        raise DatabaseUnavailable(secret)

    with TestClient(application) as client:
        response = client.get("/database-error")
    assert response.status_code == 503
    assert secret not in response.text
    assert secret not in caplog.text


@pytest.mark.parametrize(
    "exception",
    [
        OperationalError("SELECT private", {}, RuntimeError("connection-secret")),
        PoolTimeoutError("connection-secret"),
    ],
)
def test_database_connection_and_pool_failures_are_unavailable(
    application: FastAPI, exception: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    @application.get("/database-connection-error", response_model=None)
    def database_connection_error() -> NoReturn:
        raise exception

    with TestClient(application) as client:
        response = client.get("/database-connection-error")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "connection-secret" not in response.text
    assert "SELECT private" not in response.text
    assert "connection-secret" not in caplog.text


def test_unexpected_exception_is_redacted_and_correlated(
    application: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "SELECT password FROM private_credentials"

    @application.get("/unexpected-error", response_model=None)
    def unexpected_error() -> NoReturn:
        raise RuntimeError(secret)

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/unexpected-error")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert secret not in response.text
    assert secret not in caplog.text


def test_http_exception_detail_is_not_echoed(application: FastAPI) -> None:
    @application.get("/http-error", response_model=None)
    def http_error() -> NoReturn:
        raise HTTPException(400, "connection-password")

    with TestClient(application) as client:
        response = client.get("/http-error")
    assert response.status_code == 400
    assert "connection-password" not in response.text


def test_readiness_without_database_configuration() -> None:
    with TestClient(main.create_app(Settings(_env_file=None, database_url=None))) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/ready")
    assert response.status_code == 503


def test_openapi_has_stable_operation_ids_and_error_schema(application: FastAPI) -> None:
    schema = application.openapi()
    assert schema["paths"]["/health"]["get"]["operationId"] == "getHealth"
    assert schema["paths"]["/ready"]["get"]["operationId"] == "getReadiness"
    assert schema["paths"]["/version"]["get"]["operationId"] == "getVersion"
    error = schema["paths"]["/ready"]["get"]["responses"]["503"]
    assert error["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
