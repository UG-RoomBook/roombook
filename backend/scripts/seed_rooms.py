from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import Database
from app.modules.rooms.models import Room

ROOMS: tuple[dict[str, Any], ...] = (
    {
        "id": UUID("10000000-0000-4000-8000-000000000001"),
        "name": "The Studio",
        "location": "West building · Level 1",
        "capacity": 4,
        "active": True,
    },
    {
        "id": UUID("10000000-0000-4000-8000-000000000002"),
        "name": "The Forum",
        "location": "North building · Level 2",
        "capacity": 8,
        "active": True,
    },
)


def seed_rooms(session: Session) -> int:
    """Add missing reference rooms; the caller owns the transaction."""
    statement = insert(Room).values(ROOMS).on_conflict_do_nothing(index_elements=[Room.id])
    return len(session.scalars(statement.returning(Room.id)).all())


def main() -> None:
    database = Database(Settings().database_url)
    try:
        with database.session() as session, session.begin():
            inserted = seed_rooms(session)
        print(f"Inserted {inserted} rooms")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
