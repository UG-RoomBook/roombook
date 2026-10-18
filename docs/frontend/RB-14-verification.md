# RB-14 room-discovery verification

Verified locally on 18 October 2026. Application code: [826b18d](https://github.com/UG-RoomBook/roombook/commit/826b18d85b46897cc013ff9528c7af1dfac9e2ee). This records implementation evidence; Daniel's independent acceptance and visual review of states outside the approved baseline remain pending.

## Change

The pinned Hey API generator now reads `backend/openapi.json` directly. The duplicate frontend draft contract is removed. Generated operations contain only implemented room, health, readiness and version endpoints. Generation checks use temporary output and leave the checkout unchanged.

Search uses the real room endpoint, URL filters, explicit Melbourne offsets and bounded API pages. Group size filters the current page, with page-local counts. A far out-of-range offset can return to the last known page in one action. Refreshing withholds cached availability, and failures expose retry feedback and an API request ID when present. Runtime identity is hidden after a failed version refresh.

The existing booking demonstration is isolated in a provisional adapter. It runs only with development mocks or the development test environment. Real mode reports booking as unavailable without sending a booking request. Accounts, owned bookings and scheduling remain separate Jira work.

## Checks

| Check | Observed result |
| --- | --- |
| Dependency installation | Committed lockfile installed with Node 24.19.0 and npm 11.6.2 |
| Generated API, formatting, lint, strict types and build | Passed |
| Frontend tests | 97 passed across 11 files |
| First-party frontend coverage | 96.78% lines; 91.3% branches; existing generated/mock/setup exclusions retained |
| Negative generated-client drift probe | Failed as expected with exit 1; source was unchanged and exact bytes restored; subsequent check passed |
| Backend OpenAPI export check | Passed; backend source and exported contract unchanged |
| Alembic schema check | No new upgrade operations detected |
| Real API checks | 13 read-only requests passed against FastAPI and PostgreSQL |

Raw evidence: [frontend commands](rb14-frontend-checks.txt), [negative drift check](rb14-api-drift-check.txt), [API responses](rb14-api-checks.json) and [API server log](rb14-api-server.txt). Component tests use MSW; they are distinct from these real-system observations.

The API checks cover process health, database readiness, configured version, metadata without availability, interval availability, equivalent UTC/Melbourne instants, stable one-item pages, empty out-of-range pages and 422 validation envelopes. They do not create or alter rooms or bookings. The local database contains the two existing reference rooms.

## Browser observations

Vite on loopback port 5174 proxies the API on port 8001 with `VITE_ENABLE_MOCKS=false`. Both processes use the code at 826b18d; the API's configured identity is recorded in the response evidence. PostgreSQL 17 runs in the existing local development container. Bundled DM Sans and Space Grotesk fonts are unchanged.

- The real search shows The Forum and The Studio for 19 October 2026, 13:00 to 14:00 in Melbourne. Selecting eight people returns The Forum.
- An offset of 1000 shows an empty page; Previous returns to offset 0 in one action.
- A metadata-only search offers no booking until an interval is selected. The skipped Melbourne time on 4 October 2026 at 02:30 produces validation feedback.
- Light/Dark changes preserve the interval and route. Both themes show the same application boundaries with no horizontal overflow at the native 1280 x 720 viewport.
- Confirming from the prepared review screen shows the explicit unavailable message. No implemented booking flow is claimed.
- Before the final code checkpoint, the stopped local database produced a real 503 response and request ID. Restoring the existing container and retrying recovered the room list.

| Screen | Evidence |
| --- | --- |
| Search, Light | [Full-page capture](screenshots/rb14/search-light.png) |
| Search, Dark | [Full-page capture](screenshots/rb14/search-dark.png) |
| Booking unavailable, Dark | [Pending-state capture](screenshots/rb14/booking-unavailable.png) |

The browser's width override did not apply the requested 320, 390, 768, 1440 and 1920 px widths; the observed viewport remained 1280 x 720. [Measured results](rb14-responsive-checks.json) state this limitation. These captures are inspection evidence, not visual comparison baselines. The browser build number is not exposed by the available browser controls.

## Remaining verification

The immutable [v1 reference](../design/baselines/v1/README.md), SVG geometry, theme materials and layout styles are unchanged. Loading, empty, failure and unavailable states remain pending Saad's visual review. Daniel retains independent acceptance, the complete responsive/accessibility matrix, System preference changes, 200% zoom and separate motion verification in RB-25.

The build retains existing third-party annotation warnings and a 660 kB main JavaScript chunk. The dependency audit reports four high findings in the development-only Hey API/js-yaml chain; the runtime-only audit reports zero findings. Toolchain remediation remains open for the PR-check work in RB-20; no automatic dependency downgrade was applied.

The backend test suite was not changed or rerun by this frontend work; its earlier verification remains separate. Candidate images, Test-host execution, isolated Staging, Production qualification, account/booking/admin integration and release gates remain with their existing owners. Local success does not establish those outcomes.
