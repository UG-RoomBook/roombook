# RB-51 verification, 20 October 2026

Implementation source: `08266c6c20b7c11aac8b404639529a289c106529`,
branch `feat/RB-51-shared-availability`, based on main `f5e3644`.  
Owner: Saad. Independent reviewer: Daniel; acceptance remains pending.

## Observed checks

Checks used Python 3.12.14, uv 0.13.1 and the locked dependencies on Linux.
Database tests used real isolated PostgreSQL `roombook_test`. The workspace
`./dev check-api` wrapper ran the commands in the root README.

| Check | Result |
| --- | --- |
| Ruff lint and format | Passed, 70 files |
| Strict mypy | Passed, 65 source files |
| Full backend regression suite | **384 passed** |
| Backend coverage | 97.30% lines, 88.42% branches, 95.66% combined |
| Shared availability service coverage | 100% lines and branches |
| Shared policy coverage | 98.15% lines, 97.37% branches |
| Alembic model/schema drift | Passed at `0004` |
| OpenAPI implementation/export comparison | Passed, no public schema changes |
| Generated TypeScript client comparison | Passed using pinned Node/npm generator |
| Local HTTP smoke | Health/readiness 200; metadata and valid interval 200; invalid duration 422 |

Raw [backend output](evidence/RB-51-backend-checks.txt) and
[HTTP responses](evidence/RB-51-http-smoke.json) are retained. The existing
Starlette/httpx deprecation warning remains visible. The generator also reported
the existing local npm `allow-scripts` configuration warning. No warning was
suppressed. Frontend source, generated contract and deployment workflows are
unchanged; the broader frontend suite was not rerun for this backend-only slice.
There is no backend GitHub workflow yet, and the existing frontend path filter
does not run for these paths. These results are local checks, not a CI/image or
AWS deployment qualification.

## Calendar and concurrency evidence

Tests cover weekly windows, closed/date-replacement exceptions, adjacent and
overlapping windows, closure/booked boundaries, inactive/unconfirmed rooms,
cancelled bookings, cross-midnight coverage, DST gaps/folds and elapsed durations,
15-minute start alignment, inclusive duration/horizon boundaries and no-slot
results. A valid start exactly 14 elapsed days ahead may end two hours later.

Room HTTP tests verify a constant six SELECTs for 1, 25 and 100 rooms. Internal
next-slot tests verify four reads for 25 rooms, with no per-candidate SQL. Existing
response shape, metadata omission of `available`, pagination and sanitized
validation/database errors remain covered.

Separate PostgreSQL connections prove that a competing writer actually blocks
on the room row (`pg_blocking_pids`), then sees committed state under READ
COMMITTED. Three cases pass: closure then booking rejects `ROOM_UNAVAILABLE`;
booking then closure rejects `BOOKINGS_AFFECTED`; booking then booking rejects
`ROOM_UNAVAILABLE`. Existing tests still prove the database exclusion constraint
rejects active overlap and permits adjacent/cancelled intervals. Mutation tests
reject hours/exception/closure/deactivation/unconfirmation changes and confirm
rollback retains booking history. Ongoing and pre-policy long bookings are
preserved without applying new duration rules retroactively.

## Inventory, migration and rollback

The local development inventory before migration was revision `0003`, two rooms
and zero bookings. Migration `0004` and the normal seed preserved both rooms.
The explicit synthetic fixture inserted one separate room; its second run
reported existing data retained. Afterwards the local inventory was three rooms,
zero bookings and two rooms without confirmed hours.

A prior-schema test inserts an actual room and booking at `0003`, upgrades to
`0004`, verifies unchanged IDs/data and unconfirmed hours, downgrades the empty
calendar schema to `0003` and upgrades again. A populated-calendar downgrade is
rejected and leaves revision `0004` and its data intact. Fresh migration round
trips and the previous identity-data downgrade protection also pass. Seed tests
prove administrator edits and deactivation/unconfirmation are never replaced.

No Production data or hours were inspected or modified. Before any rollout,
repeat the inventory against the intended environment, reconcile ongoing/future
reservations with approved hours and follow the
[migration/rollback runbook](RB-51-availability.md#setup-and-migration-procedure).
The previous app can read the additive schema but ignores calendar policy;
rollback requires maintenance until a calendar-aware fix is available.

## Local runtime smoke and remaining work

A temporary Uvicorn process served the real development database on loopback
port 8011. Requests confirmed metadata without availability, availability of the
synthetic room on 21 October 2026 at 13:00–14:00 Melbourne, both unconfirmed
reference rooms unavailable, and a three-hour request rejected with the shared
422 policy error. The temporary process was stopped afterwards.

Daniel's independent review and RB-11/RB-13 acceptance remain pending. Actual
Production opening hours must still be confirmed. RB-15 must integrate the guard
with session ownership/idempotency and implement booking endpoints; RB-52/RB-53
must add authenticated admin/MFA/audit/preview operations; RB-54 must expose the
next-slot API/UI. Full member book/cancel browser journeys remain later core
handoff gates. The AWS delivery baseline and Prattay's pipeline scope are unchanged.
