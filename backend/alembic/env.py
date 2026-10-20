from sqlalchemy import create_engine, pool

from alembic import context
from app.core.config import Settings
from app.db.base import Base
from app.modules.availability.models import (  # noqa: F401
    Closure,
    DateException,
    ExceptionHours,
    WeeklyHours,
)
from app.modules.bookings.models import Booking, BookingRequest  # noqa: F401
from app.modules.identity.accounts import AccountAttempt  # noqa: F401
from app.modules.identity.models import ApplicationUser, AuditEvent, AuthSession, ExternalIdentity  # noqa: F401
from app.modules.rooms.models import Room  # noqa: F401

target_metadata = Base.metadata


def database_url() -> str:
    url = Settings().database_url
    if url is None:
        raise RuntimeError("Set ROOMBOOK_DATABASE_URL before running migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        database_url(),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 5, "options": "-c lock_timeout=5000"},
    )
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
