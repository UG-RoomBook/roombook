"""Opt-in localhost development fixture; never updates an existing room."""

import argparse
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import Database
from app.modules.availability.models import WeeklyHours
from app.modules.rooms.models import Room

SYNTHETIC_ROOM_ID = UUID("10000000-0000-4000-8000-000000000051")


def seed_synthetic_calendar(session: Session, settings: Settings) -> bool:
    """The caller owns the transaction. Existing edits, including closure, win."""
    if (
        settings.environment not in {"development", "test"}
        or settings.database_url is None
        or make_url(settings.database_url).host not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("Synthetic hours require a localhost development/test database")
    inserted = session.scalar(
        insert(Room)
        .values(
            id=SYNTHETIC_ROOM_ID,
            name="Synthetic development room",
            location="Local fixture — not university hours",
            capacity=4,
            active=True,
            hours_confirmed=True,
        )
        .on_conflict_do_nothing()
        .returning(Room.id)
    )
    if inserted is None:
        return False
    session.add_all(
        WeeklyHours(room_id=inserted, weekday=day, start_minute=540, end_minute=1020)
        for day in range(7)
    )
    session.flush()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true", required=True)
    parser.parse_args()
    settings = Settings()
    database = Database(settings.database_url)
    try:
        with database.session() as session, session.begin():
            inserted = seed_synthetic_calendar(session, settings)
        print(
            "Inserted synthetic 09:00–17:00 daily fixture" if inserted else "Existing data retained"
        )
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
