"""Read-only booking ownership inventory. No booking IDs or personal data are output."""

import json

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import Database
from app.modules.bookings.models import Booking


def inventory_legacy_bookings(session: Session) -> dict[str, object]:
    """Report existing unowned history; this migration never infers an owner."""
    statement = select(Booking.status, func.count()).group_by(Booking.status)
    columns = {column["name"] for column in inspect(session.connection()).get_columns("bookings")}
    if "owner_id" in columns:
        statement = statement.where(Booking.owner_id.is_(None))
    counts = dict(session.execute(statement).all())
    return {
        "ownership": "not_assigned",
        "total": sum(counts.values()),
        "by_status": {"active": counts.get("active", 0), "cancelled": counts.get("cancelled", 0)},
    }


def main() -> None:
    database = Database(Settings().database_url)
    try:
        with database.session() as session:
            print(json.dumps(inventory_legacy_bookings(session), sort_keys=True))
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
