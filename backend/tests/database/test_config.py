from unittest.mock import Mock, patch

import pytest
from fastapi import Request
from pydantic import ValidationError

from app.core.config import Settings
from app.db.session import Database, DatabaseUnavailable
from app.dependencies import get_session


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "ROOMBOOK_DATABASE_URL",
        "ROOMBOOK_ENVIRONMENT",
        "ROOMBOOK_VERSION",
        "ROOMBOOK_COMMIT_SHA",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


def test_settings_work_without_database_configuration() -> None:
    settings = Settings(database_url=None)
    assert settings.database_url is None
    assert settings.environment == "development"
    assert settings.version == "0.1.0"
    assert settings.commit_sha == "unknown"


@pytest.mark.parametrize(
    "value",
    [
        "sqlite:///test.db",
        "postgresql://localhost/test",
        "postgresql+asyncpg://localhost/test",
        "postgresql+psycopg://localhost",
        "not a URL",
    ],
)
def test_settings_reject_unsupported_database_configuration(value: str) -> None:
    with pytest.raises(ValidationError, match="PostgreSQL URL"):
        Settings(database_url=value)


def test_settings_read_prefixed_environment_and_hide_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "postgresql+psycopg://user:private@localhost/roombook"
    monkeypatch.setenv("ROOMBOOK_DATABASE_URL", url)
    monkeypatch.setenv("ROOMBOOK_ENVIRONMENT", "staging")
    monkeypatch.setenv("ROOMBOOK_COMMIT_SHA", "abc123")
    settings = Settings()
    assert settings.database_url == url
    assert settings.environment == "staging"
    assert settings.commit_sha == "abc123"
    assert "private" not in repr(settings)


def test_prefixed_database_url_takes_precedence_over_generic_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "postgresql+psycopg://localhost/roombook"
    monkeypatch.setenv("ROOMBOOK_DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/other")
    assert Settings().database_url == url


def test_unconfigured_database_is_not_ready_and_cannot_yield_session() -> None:
    database = Database(None)
    assert database.ready() is False
    with pytest.raises(DatabaseUnavailable), database.session():
        pytest.fail("An unconfigured database must not provide a session")
    database.dispose()


def test_database_construction_is_lazy_and_closes_pool() -> None:
    with patch("app.db.session.create_engine") as create_engine:
        database = Database("postgresql+psycopg://localhost/roombook")
        create_engine.return_value.connect.assert_not_called()
        database.dispose()
        create_engine.return_value.dispose.assert_called_once()


def test_request_dependency_closes_session_after_use() -> None:
    database = Database("postgresql+psycopg://localhost/roombook")
    request = Mock(spec=Request)
    request.app.state.database = database
    dependency = get_session(request)
    session = next(dependency)
    with patch.object(session, "close", wraps=session.close) as close:
        dependency.close()
        close.assert_called_once()
    database.dispose()
