"""Read-only, aggregate pre/post-migration inventory; never prints personal data."""

import json

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import Database


def inventory(session: Session) -> dict[str, int | str]:
    result: dict[str, int | str] = {
        "revision": str(session.scalar(text("SELECT version_num FROM alembic_version"))),
        "rooms": int(session.scalar(text("SELECT count(*) FROM rooms")) or 0),
        "bookings": int(session.scalar(text("SELECT count(*) FROM bookings")) or 0),
        "active_ongoing_or_future_bookings": int(
            session.scalar(
                text("SELECT count(*) FROM bookings WHERE status='active' AND ends_at > now()")
            )
            or 0
        ),
    }
    columns = {column["name"] for column in inspect(session.connection()).get_columns("rooms")}
    if "hours_confirmed" in columns:
        result["rooms_without_confirmed_hours"] = int(
            session.scalar(text("SELECT count(*) FROM rooms WHERE NOT hours_confirmed")) or 0
        )
    return result


def main() -> None:
    database = Database(Settings().database_url)
    try:
        with database.session() as session:
            print(json.dumps(inventory(session), indent=2))
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
