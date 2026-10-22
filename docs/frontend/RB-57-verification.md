# RB-57 two-hour picker verification

Verified locally on 22 October 2026. Implementation: [ad04431](https://github.com/UG-RoomBook/roombook/commit/ad04431f57ee505105bea2c1c4ad45e61d27b538), based on main 571da28. [RB-57](https://swe40006-roombook.atlassian.net/browse/RB-57) is the focused picker subtask of RB-16. Implementation and local verification are complete; PR review/merge and release acceptance remain separate.

## Behavior

The Until selector offers valid end times first and retains other same-day times in a disabled, visually muted group. A 13:00 start enables every minute from 13:30 through 15:00, including both boundaries. Minute precision is preserved; the existing 15-minute start rule is enforced. The end is not automatically set to two hours.

Changing the date/start recalculates choices, preserves a valid existing end and clears an invalid end with an accessible explanation. The end control is disabled without a valid start or any same-day endpoint. Helper text states the duration limit and latest end. Search and direct review URLs use the same duration/start validation. Generic historical interval formatting remains unchanged. Server time, the 14-day horizon, room hours and availability remain authoritative backend checks.

Elapsed arithmetic handles Melbourne daylight saving. Skipped/repeated endpoints remain invalid. A spring 01:30 start can end at 04:30 after two elapsed hours; autumn repeated endpoints are excluded. The picker never rolls an end into tomorrow. No API, database, dependency or immutable v1 archive changes are included.

## Checks

| Check | Observed result |
| --- | --- |
| Generated API drift, formatting, ESLint, TypeScript and production build | Passed with Node 24.21.0 / npm 11.19.0 |
| Full frontend suite | 145 tests passed; 96.50% first-party line coverage, 89.60% overall branch coverage, 90.54% booking-feature branch coverage |
| Existing backend availability-policy suite | 30 passed |
| Real FastAPI/PostgreSQL boundary requests | 30 and 120 minutes returned 200; 29 and 121 returned 422; readiness returned 200 |
| Native keyboard selection | End stops at 15:00 for a 13:00 start; ArrowUp selects 14:59; unavailable choices are disabled |
| Changed start | Keyboard changes preserved 15:00 while valid; a 14:45 start cleared it with an explanation |
| Search to review | Real room search and room lookup succeeded for the synthetic room, 14:45–15:15 |
| Invalid review URL | 14:45–17:00 showed the duration error and no Confirm booking button |
| Responsive checks | 375×812 portrait, 812×375 landscape and 1440×900 desktop had no horizontal overflow; Until target is 44px high |

Raw evidence: [frontend tests](evidence/RB-57/frontend-tests.txt), [frontend checks](evidence/RB-57/frontend-checks.txt), [backend tests](evidence/RB-57/backend-policy-tests.txt), [API boundaries](evidence/RB-57/api-boundaries.json), [API log](evidence/RB-57/api-server.txt) and [measured widths](evidence/RB-57/responsive.json).

## Browser evidence

| View | Capture |
| --- | --- |
| Original unrestricted 13:00–16:00 selection | [Before](evidence/RB-57/before.jpg) |
| Updated picker | [Light](evidence/RB-57/after-light.jpg), [Dark](evidence/RB-57/after-dark.jpg) |
| Phone | [Light](evidence/RB-57/mobile-light.jpg), [Dark](evidence/RB-57/mobile-dark.jpg) |
| Desktop | [Light](evidence/RB-57/desktop-light.jpg), [Dark](evidence/RB-57/desktop-dark.jpg) |
| Invalid direct URLs | [Search](evidence/RB-57/invalid-search.jpg), [Review](evidence/RB-57/invalid-review.jpg) |

The before capture was taken before starting the local API; its unavailable-service message is unrelated to the picker change. After captures use Vite on 5173, FastAPI on 8000 and the local Compose PostgreSQL database. Existing synthetic calendar data was retained. Backend runtime identity is 571da28 because backend source is unchanged. Authentication was disabled for this public discovery check; auth-session 503 responses in the log are expected in that setup. No booking was submitted, and no real opening hours or account data were modified.

The native browser option popup is not included in page screenshots; disabled semantics, grouping and keyboard selection were inspected separately. Mobile checks use a resized desktop browser, not a physical phone. The existing Vite large-chunk warning remains (approximately 674 kB main JavaScript). These local checks do not establish deployment, full owned-booking integration or independent teammate acceptance; remaining booking submission work belongs to RB-16.
