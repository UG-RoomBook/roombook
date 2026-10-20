# RB-51 availability and calendar handoff

Owner: Saad. Independent reviewer: Daniel.  
Updated: 2026-10-20. Implementation follows
[ADR-009](https://github.com/UG-RoomBook/wiki/blob/main/decisions/ADR-009-room-administration-and-scheduling.md).

## Calendar data and search

Migration `0004` adds `rooms.hours_confirmed` (default false), weekly windows,
date exceptions with replacement windows, and UTC maintenance closures. Room IDs,
bookings, cancellation history and the named booking exclusion constraint remain
unchanged. Weekly weekdays are Monday = 0 through Sunday = 6. Windows use integer
minutes from local midnight, `0 <= start < end <= 1440`. Split overnight opening
hours across days. Adjacent windows are contiguous; overlapping windows on the
same weekday or exception are rejected by PostgreSQL. An exception replaces the
whole date; an exception with no windows means closed.

Interval search now requires an active room, confirmed hours covering the entire
interval, and no overlapping closure or active booking. All intervals are
half-open `[start, end)`. Cancelled bookings do not block availability. Metadata
search still includes inactive/unconfirmed rooms and omits `available`.
Confirmation does not itself open a room: a covering window must exist.

The room page retains its existing response schema, deterministic ordering and
100-room maximum. Interval reads use six SELECTs for a nonempty page: count,
rooms, weekly hours, exceptions/windows, closures and bookings. Empty pages need
only count and rooms. No per-room queries are issued.

## Executable policy

| Rule | Boundary |
| --- | --- |
| Start | Strictly later than the server instant, including after lock acquisition |
| Alignment | Melbourne minute divisible by 15, zero seconds/microseconds |
| Duration | Actual elapsed time, inclusive 30 minutes through 120 minutes |
| Horizon | Start at or before `now + 14 * 24 hours`; end may be up to two hours later |
| Local times | Reject skipped or repeated Melbourne wall-clock selections |
| Offset input | Normalize explicit-offset/UTC instants; reject endpoints in the repeated Melbourne hour even if an offset disambiguates them |
| Recurring hours at DST | A window whose boundary lands in a skipped/repeated hour is unavailable for that date |

An explicit-offset timestamp represents an instant, not a timezone identifier.
It is normalized to Melbourne before policy checks. Use `local_instant` when
converting a local selection or validating proposed dated schedule boundaries;
it round-trips both folds and rejects nonexistent/ambiguous times. Do not attach
a Melbourne timezone to a naive datetime and silently accept the result. The
frontend's existing Temporal conversion rejects these selections too.

Policy violations return the existing 422 `VALIDATION_ERROR` envelope with a
`booking_policy` detail. Search availability is advisory until booking commits.
No booking or public next-slot endpoint is introduced by this ticket.

`next_slots` accepts a bounded room page and duration, captures one `now`, loads
four calendar datasets through the horizon plus maximum duration, then scans
15-minute UTC candidates without further SQL. It returns the earliest full
interval at/after `not_before` (and strictly after `now`), or `None`. Each room
has at most 1,345 candidates. DST gaps and repeated endpoints are skipped using
the same validator. RB-54 supplies the public API/UI integration.

## One transaction for every availability writer

Use `locked_room(session, room_id)` with a clean, dedicated SQLAlchemy session.
It owns the transaction, requires PostgreSQL READ COMMITTED, refreshes the room
under `SELECT ... FOR UPDATE`, and commits only after checking preservation of
all active ongoing/future bookings. Do not begin, commit or roll back a different
transaction inside it, cache its guard, or write availability before entering.
The helper rejects a pre-existing transaction and guard reuse after completion.

Within that block, booking creation must call `guard.require_available(start,
end)` immediately before insertion and store the returned normalized instants.
Booking identity, ownership, payload-bound idempotency, replay responses and audit
work belong inside the same transaction in RB-15. Preserve and map the existing
`bookings_active_room_interval_excl` constraint as the final book/book guarantee.
The helper is an internal service contract, not a database authorization policy;
raw SQL writers bypass it and must not be introduced by later features.

Schedule, date-exception, closure, confirmation and deactivation writes use the
same block. On exit, the helper flushes the proposed changes and rejects changes
that remove calendar support for ongoing/future active reservations with
`BOOKINGS_AFFECTED` (409), rolling the whole transaction back. It does not cancel
or delete bookings. Existing reservations do not retroactively acquire the new
duration, horizon, alignment or endpoint restrictions. Completed history remains
stored and does not block later schedule edits.

RB-52/RB-53 must add admin/MFA authorization, mutation previews, reason/actor audit
records and reviewed screens around this boundary. These controls are not
supplied by the internal guard, and there are no public schedule mutation routes
in RB-51.

## Setup and migration procedure

Run these commands from `backend/` using the intended environment configuration.
The inventory supports both revisions `0003` and `0004`, printing only aggregate
counts and the migration revision.

```text
uv run --locked python -m scripts.inventory_calendars
uv run --locked alembic upgrade head
uv run --locked python -m scripts.seed_rooms
uv run --locked python -m scripts.inventory_calendars
uv run --locked alembic check
```

Before any shared-environment rollout, retain a verified backup and record the
inventory. Review every existing ongoing/future booking against the approved
hours; resolve conflicts explicitly without cancellation or owner reassignment
by migration. Migration does not backfill hours. All pre-existing rooms become
unavailable in interval searches until their real hours are confirmed through a
reviewed operator/admin process. Production hours are still unconfirmed; this
change is not a Production qualification.

For opt-in localhost development/test only:

```text
uv run --locked python -m scripts.seed_synthetic_calendar --synthetic
```

This atomically inserts one separately named **Synthetic development room** with
09:00–17:00 daily fixture hours. The stable ID ends in `0051`. The command refuses
non-localhost databases and environments other than `development`/`test`. It
never updates an existing room or calendar, even if those hours were edited or
confirmation was removed. It does not change the two reference rooms.
Normal `seed_rooms` runs never create hours or replace administrator edits.

## Rollback and release limits

An empty-calendar `0004 -> 0003 -> 0004` round trip preserves original room and
booking data. Downgrade refuses if calendars or confirmation flags are populated.
Do not clear them to force a rollback; retain the additive schema and recover
through a reviewed forward fix or backup procedure.

The previous application can read the additive schema, but it ignores calendar
rules. **Do not roll back to the old availability implementation while serving
booking/search traffic.** Put the service into maintenance, preserve schema/data,
and deploy a calendar-aware fix before reopening traffic. This is structural
schema compatibility, not permission to bypass the new policy.

AWS Compose packaging, CI/CD and deployment remain Prattay's pipeline work under
ADR-012. RB-15/RB-16 and RB-17/RB-18 still supply owned booking and cancellation;
RB-52/RB-53/RB-54 supply the later admin and next-slot experiences. Independent
review, actual Production hours and live deployment acceptance remain pending.
