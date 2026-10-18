import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import Database
from app.modules.rooms.models import Room

pytestmark = pytest.mark.database


def test_database_readiness_and_request_sessions_are_independent(
    database_url: str, clean_database: None
) -> None:
    database = Database(database_url)
    try:
        assert database.ready() is True
        with database.session() as first, database.session() as second:
            assert first is not second
            assert first.scalar(text("SELECT 1")) == 1
            assert second.scalar(text("SELECT 1")) == 1
    finally:
        database.dispose()


def test_session_exit_rolls_back_uncommitted_work(
    database_url: str, db_engine: Engine, clean_database: None
) -> None:
    database = Database(database_url)
    try:
        with pytest.raises(RuntimeError, match="abort"), database.session() as session:
            session.add(Room(name="Uncommitted", location="Test", capacity=4))
            session.flush()
            raise RuntimeError("abort")
        with Session(db_engine) as verification:
            assert verification.scalar(select(Room).where(Room.name == "Uncommitted")) is None
    finally:
        database.dispose()


def test_database_queries_have_a_statement_timeout(database_url: str, clean_database: None) -> None:
    database = Database(database_url)
    try:
        with database.session() as session:
            assert session.scalar(text("SHOW statement_timeout")) == "2s"
            with pytest.raises(OperationalError, match="statement timeout"):
                session.execute(text("SELECT pg_sleep(3)"))
    finally:
        database.dispose()


def test_unreachable_database_reports_not_ready() -> None:
    database = Database("postgresql+psycopg://roombook:roombook@127.0.0.1:1/roombook_test")
    try:
        assert database.ready() is False
    finally:
        database.dispose()
