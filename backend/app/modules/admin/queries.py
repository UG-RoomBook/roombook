from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.modules.admin.schemas import (
    Activity,
    AdminBooking,
    AdminRoom,
    AdminUser,
    BookingPage,
    ClosureInput,
    ExceptionInput,
    HoursInput,
    Overview,
    Page,
    PageQuery,
    ScheduleRead,
    WeeklyInput,
)
from app.modules.availability.models import Closure, DateException, ExceptionHours, WeeklyHours
from app.modules.availability.policy import CAMPUS
from app.modules.bookings.models import Booking
from app.modules.identity.models import ApplicationUser, AuditEvent
from app.modules.rooms.models import Room


def room(db: Session, room_id: UUID) -> Room:
    item = db.get(Room, room_id)
    if item is None:
        raise ApiError(404, "ROOM_NOT_FOUND", "The room was not found.")
    return item


def schedule(db: Session, item: Room) -> ScheduleRead:
    windows: dict[UUID, list[HoursInput]] = {}
    exceptions = list(
        db.scalars(
            select(DateException)
            .where(DateException.room_id == item.id)
            .order_by(DateException.date)
        )
    )
    for window in db.scalars(
        select(ExceptionHours)
        .join(DateException)
        .where(DateException.room_id == item.id)
        .order_by(ExceptionHours.start_minute)
    ):
        windows.setdefault(window.exception_id, []).append(
            HoursInput(start_minute=window.start_minute, end_minute=window.end_minute)
        )
    return ScheduleRead(
        room_id=item.id,
        revision=item.revision,
        hours_confirmed=item.hours_confirmed,
        weekly=[
            WeeklyInput(weekday=w.weekday, start_minute=w.start_minute, end_minute=w.end_minute)
            for w in db.scalars(
                select(WeeklyHours)
                .where(WeeklyHours.room_id == item.id)
                .order_by(WeeklyHours.weekday, WeeklyHours.start_minute)
            )
        ],
        exceptions=[ExceptionInput(date=e.date, windows=windows.get(e.id, [])) for e in exceptions],
        closures=[
            ClosureInput(starts_at=c.starts_at, ends_at=c.ends_at, reason=c.reason)
            for c in db.scalars(
                select(Closure)
                .where(Closure.room_id == item.id)
                .order_by(Closure.starts_at, Closure.id)
            )
        ],
    )


def rooms(db: Session, page: PageQuery, search: str = "") -> Page[AdminRoom]:
    query = select(Room).where(
        or_(
            Room.name.icontains(search, autoescape=True),
            Room.location.icontains(search, autoescape=True),
        )
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    return Page(
        items=[
            AdminRoom.model_validate(r)
            for r in db.scalars(
                query.order_by(Room.name, Room.id).offset(page.offset).limit(page.limit)
            )
        ],
        total=total,
        **page.model_dump(),
    )


def users(db: Session, page: PageQuery, search: str = "") -> Page[AdminUser]:
    query = select(ApplicationUser).where(
        or_(
            ApplicationUser.verified_email.icontains(search, autoescape=True),
            cast(ApplicationUser.id, String).icontains(search, autoescape=True),
        )
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    return Page(
        items=[
            AdminUser.model_validate(u)
            for u in db.scalars(
                query.order_by(ApplicationUser.created_at.desc(), ApplicationUser.id)
                .offset(page.offset)
                .limit(page.limit)
            )
        ],
        total=total,
        **page.model_dump(),
    )


def booking_view(booking: Booking, name: str, email: str | None, now: datetime) -> AdminBooking:
    return AdminBooking(
        id=booking.id,
        room_id=booking.room_id,
        room_name=name,
        owner_id=booking.owner_id,
        owner_label=email
        or ("Legacy booking" if booking.owner_id is None else str(booking.owner_id)),
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        created_at=booking.created_at,
        cancelled_at=booking.cancelled_at,
        status="Cancelled"
        if booking.status == "cancelled"
        else "Completed"
        if booking.ends_at <= now
        else "Upcoming"
        if booking.starts_at > now
        else "Ongoing",
    )


def booking_query() -> Select[Booking, str, str | None]:
    return (
        select(Booking, Room.name, ApplicationUser.verified_email)
        .join(Room)
        .outerjoin(ApplicationUser, ApplicationUser.id == Booking.owner_id)
    )


def booking(db: Session, booking_id: UUID, now: datetime) -> AdminBooking:
    row = db.execute(booking_query().where(Booking.id == booking_id)).one_or_none()
    if row is None:
        raise ApiError(404, "BOOKING_NOT_FOUND", "The booking was not found.")
    return booking_view(row[0], row[1], row[2], now)


def bookings(
    db: Session,
    page: PageQuery,
    now: datetime,
    status: str = "all",
    room_id: UUID | None = None,
    search: str = "",
    day: datetime | None = None,
    *,
    active_only: bool = False,
) -> BookingPage:
    query = booking_query()
    if active_only:
        query = query.where(Booking.status == "active")
    if status == "cancelled":
        query = query.where(Booking.status == "cancelled")
    elif status != "all":
        query = query.where(Booking.status == "active")
        if status == "upcoming":
            query = query.where(Booking.starts_at > now)
        elif status == "ongoing":
            query = query.where(Booking.starts_at <= now, Booking.ends_at > now)
        elif status == "completed":
            query = query.where(Booking.ends_at <= now)
    if room_id:
        query = query.where(Booking.room_id == room_id)
    if search:
        query = query.where(
            or_(
                Room.name.icontains(search, autoescape=True),
                ApplicationUser.verified_email.icontains(search, autoescape=True),
                cast(Booking.id, String).icontains(search, autoescape=True),
            )
        )
    if day:
        query = query.where(
            Booking.starts_at < day + timedelta(days=1),
            Booking.ends_at > day,
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(Booking.starts_at, Booking.id).offset(page.offset).limit(page.limit)
    )
    return BookingPage(
        generated_at=now,
        items=[booking_view(row[0], row[1], row[2], now) for row in rows],
        total=total,
        **page.model_dump(),
    )


def activity(
    db: Session,
    page: PageQuery,
    action: str = "",
    target: UUID | None = None,
    actor: UUID | None = None,
) -> Page[Activity]:
    query = select(AuditEvent, ApplicationUser.verified_email).outerjoin(
        ApplicationUser, ApplicationUser.id == AuditEvent.actor_user_id
    )
    if action:
        query = query.where(AuditEvent.action.icontains(action, autoescape=True))
    if target:
        query = query.where(AuditEvent.target_id == target)
    if actor:
        query = query.where(AuditEvent.actor_user_id == actor)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    allowed = {"reason", "before", "after", "count", "purpose", "operator", "environment"}
    return Page(
        items=[
            Activity(
                id=e.id,
                actor_user_id=e.actor_user_id,
                actor_label=email or (str(e.actor_user_id) if e.actor_user_id else "Operator"),
                target_id=e.target_id,
                action=e.action,
                occurred_at=e.occurred_at,
                details={k: v for k, v in e.details.items() if k in allowed},
            )
            for e, email in db.execute(
                query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id)
                .offset(page.offset)
                .limit(page.limit)
            )
        ],
        total=total,
        **page.model_dump(),
    )


def overview(db: Session, now: datetime) -> Overview:
    day = datetime.combine(now.astimezone(CAMPUS).date(), time.min, CAMPUS)
    agenda = bookings(db, PageQuery(limit=8), now, day=day, active_only=True)
    return Overview(
        generated_at=now,
        active_rooms=db.scalar(select(func.count()).select_from(Room).where(Room.active)) or 0,
        active_users=db.scalar(
            select(func.count()).select_from(ApplicationUser).where(ApplicationUser.is_active)
        )
        or 0,
        bookings_today=agenda.total,
        unconfirmed_rooms=db.scalar(
            select(func.count()).select_from(Room).where(Room.hours_confirmed.is_(False))
        )
        or 0,
        agenda=agenda.items,
        recent_activity=activity(db, PageQuery(limit=5)).items,
    )
