from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.core.config import Settings

INDEX = '<!doctype html><div id="root"></div>'


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "assets" / "app-1a2b3c.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path.parent / "outside-secret.txt").write_text("secret", encoding="utf-8")
    return tmp_path


@pytest.fixture
def packaged(static_dir: Path) -> FastAPI:
    # No database is configured, so data routes answer 503 instead of reaching PostgreSQL.
    return main.create_app(
        Settings(
            _env_file=None,
            database_url=None,
            environment="test",
            commit_sha="b" * 40,
            static_dir=static_dir,
        )
    )


@pytest.mark.parametrize("path", ["/", "/rooms", "/bookings/123", "/find?size=4"])
def test_client_routes_receive_the_app_shell(packaged: FastAPI, path: str) -> None:
    with TestClient(packaged) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


def test_api_and_operational_routes_take_precedence(packaged: FastAPI) -> None:
    with TestClient(packaged) as client:
        assert client.get("/health").json() == {"status": "healthy"}
        assert client.get("/version").json()["commit_sha"] == "b" * 40
        rooms = client.get("/api/v1/rooms")
        assert rooms.status_code == 503
        assert rooms.headers["content-type"] == "application/json"


@pytest.mark.parametrize("path", ["/api", "/api/missing", "/api/v1/missing"])
def test_unknown_api_paths_stay_json_404(packaged: FastAPI, path: str) -> None:
    with TestClient(packaged) as client:
        response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_fingerprinted_assets_are_cached_and_other_files_revalidate(packaged: FastAPI) -> None:
    with TestClient(packaged) as client:
        asset = client.get("/assets/app-1a2b3c.js")
        icon = client.get("/favicon.svg")
    assert asset.text == "console.log(1)"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert icon.headers["cache-control"] == "no-cache"


def test_paths_cannot_escape_the_static_directory(packaged: FastAPI) -> None:
    with TestClient(packaged) as client:
        response = client.get("/%2e%2e/outside-secret.txt")
    assert "secret" not in response.text


def test_static_directory_without_index_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="index.html"):
        main.create_app(Settings(_env_file=None, database_url=None, static_dir=tmp_path))


def test_frontend_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROOMBOOK_STATIC_DIR", raising=False)
    app = main.create_app(Settings(_env_file=None, database_url=None))
    with TestClient(app) as client:
        response = client.get("/rooms")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


def test_fallback_is_not_part_of_the_api_schema(packaged: FastAPI) -> None:
    assert "/{path}" not in packaged.openapi()["paths"]
