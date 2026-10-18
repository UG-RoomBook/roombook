from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


class DatabaseUnavailable(Exception):
    """The database is unavailable or has not been configured."""


class Database:
    def __init__(self, url: str | None) -> None:
        self.engine: Engine | None = None
        self._sessions: sessionmaker[Session] | None = None
        if url is not None:
            self.engine = create_engine(
                url,
                pool_size=5,
                max_overflow=0,
                pool_timeout=1,
                pool_pre_ping=True,
                connect_args={
                    "connect_timeout": 2,
                    "options": "-c statement_timeout=2000 -c lock_timeout=1000 -c timezone=UTC",
                },
            )
            self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        if self._sessions is None:
            raise DatabaseUnavailable("Database is not configured")
        with self._sessions() as session:
            yield session

    def ready(self) -> bool:
        if self.engine is None:
            return False
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SET LOCAL statement_timeout = 1000"))
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return False
        return True

    def dispose(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
