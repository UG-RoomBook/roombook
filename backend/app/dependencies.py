from collections.abc import Generator
from typing import cast

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.session import Database


def get_session(request: Request) -> Generator[Session, None, None]:
    database = cast(Database, request.app.state.database)
    with database.session() as session:
        yield session
