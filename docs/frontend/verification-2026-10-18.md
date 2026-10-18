# Frontend verification, 18 October 2026

This records the frontend implementation for RB-12 and UI preparation for RB-14, RB-16 and RB-18. Real FastAPI/PostgreSQL integration and designated teammate acceptance remain pending.

## Environment

- Windows, Node 24.19.0, npm 11.6.2, Vite 7.3.7.
- In-app Chromium browser. Its browser build number is not exposed by the browser tool, so these captures are inspection evidence rather than reproducible visual test baselines.
- Bundled DM Sans and Space Grotesk fonts. Explicit development-only MSW sample data, identified by the footer. Search interval: 19 October 2026, 13:00 to 14:00 in Australia/Melbourne.
- The approved [v1 archive](../design/baselines/v1/README.md) is unchanged. SVG shape/gradient attributes and theme material rules are checked against that archive. Production code uses instance-specific SVG IDs.

## Checks

The clean dependency install, generated-client check, formatting, lint, strict types, frontend tests and production build passed locally. The frontend suite contains 76 cases. First-party measured line coverage is 95.97%; generated SDK files, mocks, test setup and the application entry point are excluded. Coverage is frontend-only.

One local V8 coverage process crashed during an initial run. The complete rerun passed. The build reports a 659 kB main JavaScript chunk and removes two invalid third-party PURE comment annotations. These warnings do not fail the build.

Browser inspection covered:

- Search, review, confirmation, shared bookings and cancellation using development data.
- Cancellation dismissal with Escape, restored button focus, route heading focus and scroll reset.
- Light/Dark switching with preserved search values and route; persisted appearance after reload.
- Search, review and bookings in both themes at 320, 390, 768, 1440 and 1920 px. The [30 measurements](responsive-checks.json) show no document overflow or out-of-bounds checked panels after the narrow SVG container fixes.
- No browser errors or warnings were reported during these checks.

System preference changes and reduced-motion handling have component tests. Full real-browser accessibility, 200% zoom, motion verification and reviewed screenshot comparison gates remain RB-25 work. These checks do not constitute a WCAG audit.

## Screenshots

These are implementation evidence, not replacements for approved references.

| Screen | Theme | Capture |
| --- | --- | --- |
| Search | Light | [1440 x 1100](screenshots/search-light-1440.jpg) |
| Search | Dark | [1440 x 1100](screenshots/search-dark-1440.jpg) |
| Booking review | Light | [390 x 1300](screenshots/review-light-390.jpg) |
| Bookings after cancellation | Dark | [768 x 1100](screenshots/bookings-dark-768.jpg) |

Loading, empty, failure, timeout and conflict visuals remain pending visual review. The provisional OpenAPI contract must be reconciled with Daniel's backend export. A timeout can leave a booking outcome uncertain; the UI blocks another matching submission, but backend reconciliation or persisted idempotency is needed for complete timeout acceptance.
