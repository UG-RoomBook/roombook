# Room-first booking correction

Status: implemented locally; live Jira reconciliation and deployed Staging acceptance remain pending. This is a correction to the journey delivered for RB-57 and RB-16, not a change to booking ownership, email or administration.

## Accepted journey (22 October 2026)

Browse rooms → choose an active room → choose date → choose start/end → review → confirm.

The list keeps group-size filtering and bounded pagination. It no longer uses a global date/time interval. `/rooms/:roomId` defaults to today in Australia/Melbourne, with no start or end selected. Public schedules expose availability only. Confirmation still requires a verified, active account.

The picker shows quarter-hour choices in labelled native radio groups, grouped into collapsible periods. Unavailable choices are disabled and include text. Each start needs at least one continuous 30-minute interval. End choices keep the entire interval free and within 30–120 elapsed minutes on the selected Melbourne date. Range decoration is supplementary; the selected labels and textual duration communicate the selection independently of colour.

For a 10:45–11:15 reservation, a 10:00 start allows 10:30 and 10:45 ends; 10:30 cannot start a new 30-minute booking; 11:15 can start an adjacent booking. No next-slot suggestions are introduced.

Dates clear both times. Start changes retain an end only when it remains valid. URL selections survive refresh and navigation. Review's Change time returns to the same room. A fresh day response is required to review. Refresh/error states cannot masquerade as occupied slots. An invalidated end is cleared with an explanation. Query keys and cancellation isolate responses by room/date.

Availability refreshes on focus and every 30 seconds while visible; booking and cancellation invalidate the shared room keys. Server evaluation time plus the elapsed age of the response prevents a now-past start from enabling review. The server remains authoritative at creation.

## API and policy

- `GET /api/v1/rooms/{room_id}` returns direct metadata. Optional paired `starts_at` / `ends_at` return an availability boolean and preserve existing minute-precision end support.
- `GET /api/v1/rooms/{room_id}/availability?date=YYYY-MM-DD` returns room metadata, local date, `Australia/Melbourne`, evaluation time, the 14-day start-window end, and 96 start choices. Choices include explicit offset-aware timestamps, disabled reason and valid quarter-hour ends.
- Each day request selects the room once and loads the four calendar datasets once. All candidate evaluation is in memory through the existing availability policy: activity, confirmed hours, weekly hours, date exceptions, closures, active overlaps, advance window, elapsed duration and DST endpoint rejection.
- Public responses contain no reservation IDs, member details or closure reasons. Direct/day responses use `Cache-Control: no-store`.
- Review uses the direct endpoint rather than walking the room catalog. OpenAPI and the TypeScript SDK are regenerated.
- No migration or create-booking API change. The locked READ COMMITTED recheck, exclusion constraint, ownership, CSRF and persisted idempotency remain authoritative.
- On conflict the schedule refreshes; the user chooses any different interval. Pending or uncertain attempts disable Change time and retain explicit retry of the same user/key/payload. Receipt replay does not create another booking.

## Verification

- Backend: 455 tests and 96.01% combined statement/branch coverage, including boundaries, gaps, adjacency, cancellation, inactivity/unconfirmed hours, closed dates, exceptions/closures, past starts, exact 14-day boundary, both Melbourne DST changes, direct lookup and exactly five SELECTs for 96 starts.
- Frontend: 152 tests; 96.41% line coverage and 88.91% branch coverage. Tests cover list capacity/pagination, empty selection, duration bounds, URL/history restoration, invalidation, stale date responses, keyboard selection, focus/30-second refresh, sign-in preservation, confirmation/conflict and uncertain-outcome reconciliation.
- Browser: all seven journeys pass against real built React + FastAPI + PostgreSQL through `tests.e2e_server`. Only the external identity provider is synthetic. Includes authenticated confirmation/receipt reload, another session winning the same interval, and a real successful transaction whose HTTP response is deliberately dropped before the original request is retried.
- Browser layout assertions and screenshots cover 390px mobile and 1440px desktop in Light and Dark. Native radios support keyboard selection; labelled statuses and visible focus remain. These are implementation checks, not a claim of a full accessibility audit or approval of a new design baseline.

The new reusable `room-booking.yml` workflow runs the authenticated fixture journeys on PRs and gates the existing candidate image build. Public discovery tests still run against the candidate and Staging. The fixture module lives under backend tests, is excluded from the production image, binds only to loopback and refuses nonempty or non-loopback databases without a `_e2e_test` suffix. It never alters real room hours or creates live accounts.

## Release and Jira acceptance gate

Do not mark the correction complete until the existing pipeline deploys the reviewed commit and a controlled Staging account completes the positive flow on a room with operator-confirmed hours. Record deployed SHA, pipeline URL, room/date, non-sensitive booking reference and results. Retain historical RB-57/RB-16 PR and test evidence; append the correction and new acceptance criteria rather than rewriting the history as though the room-first picker existed then.

Linked acceptance updates to reconcile with Jira:

| Ticket | Correction / acceptance |
| --- | --- |
| RB-57 | Apply the two-hour cap to the selected room's start/end buttons. Only 30–120 elapsed minute continuous intervals can proceed. The old global dropdown implementation remains historical evidence. |
| RB-16 | Room list → schedule → selected slots → review → authenticated confirmation. Direct room lookup; Change time; URL/sign-in preservation; fresh reads; conflict refresh; original safe retry and receipt behavior. |
| RB-54 | Room-specific current availability is supplied by the day endpoint. Preserve the separate future next-slot work; automatic next-slot suggestions are explicitly outside this correction. |

At the time of local verification the browser integration exposed no browser session; the Jira connector exposed only a different Atlassian site and the GitHub connector returned 404 for this repository. Git CLI remains available for publishing reviewable changes. Jira changes and live acceptance must be verified once the signed-in project browser is restored; no completion status is claimed from local tests alone.
