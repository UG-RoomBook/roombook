import os
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("ROOMBOOK_TEST_DATABASE_URL")
    if not value:
        pytest.fail("Set ROOMBOOK_TEST_DATABASE_URL to run real PostgreSQL tests")
    url = make_url(value)
    if url.drivername != "postgresql+psycopg" or not (url.database or "").endswith("_test"):
        pytest.fail("Database tests require a dedicated PostgreSQL database ending in _test")
    return value


@pytest.fixture(scope="session")
def db_engine(database_url: str) -> Iterator[Engine]:
    # This fixture resets only the explicitly selected isolated test database.
    with patch.dict(os.environ, {"ROOMBOOK_DATABASE_URL": database_url}):
        config = Config("alembic.ini")
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    engine = create_engine(database_url, connect_args={"connect_timeout": 3})
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def clean_database(db_engine: Engine) -> Iterator[None]:
    with db_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE auth_sessions, audit_events, external_identities, "
                "application_users, bookings, rooms"
            )
        )
    try:
        yield
    finally:
        with db_engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE auth_sessions, audit_events, external_identities, "
                    "application_users, bookings, rooms"
                )
            )


@pytest.fixture
def db_session(db_engine: Engine, clean_database: None) -> Iterator[Session]:
    with db_engine.connect() as connection, connection.begin() as transaction:
        with Session(bind=connection) as session:
            yield session
        transaction.rollback()
