# RB-15: Owned booking creation and safe retries

Status: Implemented; local verification passed
Owner: Saad
Updated: 2026-10-21

## HTTP contract

`POST /api/v1/bookings` (`createBooking`) creates an active booking for the
verified, active user of a standard server session. Member and Admin accounts
use the same owned-booking path. Recovery, revoked, expired and inactive sessions
cannot book. The request needs the opaque HttpOnly session cookie, the exact
configured `Origin`, current `X-CSRF-Token`, and a UUID `Idempotency-Key`.

The JSON body contains only `room_id`, `starts_at` and `ends_at`. Timestamps must
be ISO 8601 with explicit offsets. Extra fields, including `owner_id` and
`status`, are rejected. Time values and UUID spelling are normalized before
payload comparison. The response contains `id`, `room_id`, `owner_id`,
`starts_at`, `ends_at`, `status` and `created_at`. All responses, including
validation, authentication and unexpected errors, are private and `no-store`.

| Status | Meaning |
| --- | --- |
| 201 | Booking created, or original successful result replayed |
| 401 | Sign-in required, invalid/revoked/expired session |
| 403 | Inactive/recovery account, wrong or missing Origin/CSRF |
| 404 | Room does not exist |
| 409 `ROOM_UNAVAILABLE` | Room is unavailable or overlaps an active booking |
| 409 `IDEMPOTENCY_MISMATCH` | This user's key already completed with another payload |
| 409 `REQUEST_IN_PROGRESS` | This user/key is currently executing; retry the same request later |
| 409 `BOOKING_BUSY` | Lock timeout or transaction contention; retry the same request later |
| 422 | Invalid fields/key/interval or booking-policy violation |
| 503 | Database or identity service unavailable; result may need reconciliation |

The [RB-51 policy](RB-51-availability.md) applies immediately after acquiring the
room lock: future 15-minute Melbourne starts, 30–120 elapsed minutes, start no
more than 14 elapsed days ahead, confirmed room hours, replacement exceptions,
closures, activity and active overlaps. PostgreSQL's named
`bookings_active_room_interval_excl` remains the final overlap guarantee. The
interval is half-open, so adjacent bookings are valid.

## Retry and timeout reconciliation

Generate one UUID per logical submission and retain it with the exact payload
until the outcome is known. Never change the key merely because a request times
out. After a network timeout, 503, `REQUEST_IN_PROGRESS` or `BOOKING_BUSY`, wait
briefly and repeat the same key and payload with a current valid session and CSRF
value. Use bounded backoff (for example 1, 2, then 4 seconds) and then offer an
explicit same-attempt retry. Validation and business conflicts are not automatic
retries. A changed user must not inherit another user's pending attempt.

Keys are scoped to the application user, not to a browser session. A fresh login
by the same user can reconcile a lost response. Another user cannot retrieve or
collide with that user's result by knowing the key. Successful keys and original
201 bodies remain stored with booking history **without automatic expiry or key
reuse**. A future retention/purge policy must explicitly preserve this guarantee.
There is no cleanup job in this slice.

Replays return the original create result even if the slot is now past or the
booking was subsequently cancelled. They are confirmation of the original
operation, not a fresh status read. RB-17 supplies current private history.
Failures before commit roll back the booking, audit and retry record together;
they do not consume the key. No durable pending state survives a crashed process.

## Transaction and concurrency

The service owns one READ COMMITTED transaction. Lock order is the per-user/key
PostgreSQL transaction advisory lock, the active user's shared row lock, then the
room row. A busy advisory lock returns promptly. A hash collision can only cause
a transient busy response; result lookup always uses the full user/key pair.

A successful replay is resolved before calendar/time validation. A new attempt
uses `room_in_transaction`, the same guard used by RB-51's `locked_room` wrapper.
The wrapper still owns its transaction for schedule writers; the composable form
requires an existing service-owned transaction. No inner commit is allowed.
Booking, persisted original response and `booking.created` audit commit once.
The user lock serializes deactivation against the final active-user check.

Every future room schedule or booking writer must continue to use the room-row
boundary. Calendar writers reject changes that invalidate ongoing/future active
bookings. Only the named exclusion conflict maps to `ROOM_UNAVAILABLE`; unrelated
integrity failures do not masquerade as a normal availability conflict.

## Migration, existing data and recovery

Migration `0005` adds nullable `bookings.owner_id`, an owner/history index and
`booking_requests`. It preserves every existing booking, room ID, status and
time. Existing unowned rows remain unowned; **no owner is inferred or assigned**.
Their active reservations still block availability. Private history/cancellation
must filter by authenticated ownership when implemented in RB-17. An unowned
row needs an explicit supported reconciliation process, not an arbitrary claim.

Before a shared-environment migration, retain a verified backup and record
aggregate inventories using the target environment's existing configuration:

```bash
uv run --locked python -m scripts.inventory_legacy_bookings
uv run --locked python -m scripts.inventory_calendars
uv run --locked alembic upgrade head
uv run --locked python -m scripts.inventory_legacy_bookings
uv run --locked python -m scripts.inventory_calendars
uv run --locked alembic check
```

The inventory supports both prior and upgraded schemas, reports
only unowned counts after upgrade, and does not output user IDs or mutate data.

For local workspace development use `./dev migrate` from the workspace root.
Existing reference rooms remain unconfirmed; only the explicit synthetic calendar
seed is suitable for local booking tests. Never infer university opening hours.

An empty ownership/retry schema can downgrade to `0004` without losing unowned
history. A populated downgrade refuses to discard ownership or retry records.
Application rollback must retain the additive schema and disable create traffic
if the older version cannot preserve retries. Restore matching booking and retry
records together; restoring one without the other can break reconciliation.
Prefer a forward fix after investigating an uncertain result. Do not clear keys,
reset live data or delete history to make a retry or downgrade succeed.

## Scope and next slice

This slice supplies backend creation and its generated client operation. RB-16
will connect the booking form, persist the pending attempt within the signed-in
user's browser flow, reconcile timeouts and invalidate availability after success.
RB-17/RB-18 cover private history and cancellation. AWS source/pipeline changes
already on main are retained; local tests do not qualify an AWS deployment.
