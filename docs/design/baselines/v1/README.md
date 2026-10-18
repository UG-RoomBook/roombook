# RoomBook design baseline v1

Saad approved this frontend design, including the detailed room SVG illustrations, on 18 October 2026. This archive records visual approval. It does not establish application completion, team review or accessibility conformance.

The [engineering wiki](https://github.com/UG-RoomBook/wiki) maintains the frontend specification and ADR-007. The companion documentation PR links this archive by immutable commit. Keep visual principles in the wiki and the original prototype here.

## Contents

| File | Purpose |
| --- | --- |
| [approved-prototype.html](approved-prototype.html) | Original approved HTML fragment, unchanged byte for byte |
| [preview.html](preview.html) | Standalone document wrapping that fragment and its preview runtime |
| [manifest.json](manifest.json) | Approval, source and screenshot hashes, capture environment, dependencies, sample data and limitations |
| [screenshots](screenshots/) | Search, booking review and bookings in both themes at 390, 768 and 1440 CSS px |

The source SHA-256 must remain `E06C135E1AA1EF6DEFB666E874ED995D7ADA1B3FC4714FE7BBD147EE3529F130`. The local attributes file disables Git text conversion for this directory so checkout preserves archived bytes.

## Open the preview

Download or clone this repository and open `preview.html` in a modern Chromium browser. GitHub displays HTML source rather than running it. For consistent origin and storage behaviour, run this command from the repository root with Python 3:

```text
python -m http.server 8000 --bind 127.0.0.1 --directory docs/design/baselines/v1
```

Open `http://127.0.0.1:8000/preview.html`. Internet access is needed for Google Fonts and the versioned script dependencies listed in the manifest. No application server or database is required. Preview interactions affect local sample state only.

Normal preview mode remembers appearance and supported demo state in browser storage. For a fresh reference state, append `?reference=search&theme=light`. The reference values are `search`, `review`, and `bookings`; themes are `light` and `dark`. Reloading a reference URL restores fixed seed data and the selected screen. Use normal mode to inspect System appearance and interaction persistence.

The standalone export removes only the outer preview margin so its iframe width equals the requested viewport. Its wrapper also supplies the reference query mode. The embedded approved fragment is unchanged apart from export line-ending normalization; the separate source file retains its original bytes. The wrapper's state bridge, styling and icon runtime are preview dependencies, not proposed application architecture.

## Reference screenshots

These are browser captures of the approved prototype, not generated mockup images or installed visual CI baselines. Each file uses device scale 1 and contains the full application boundary. Heights follow content and are recorded in the manifest.

| Screen | 390 px | 768 px | 1440 px |
| --- | --- | --- | --- |
| Search, light | [View](screenshots/search-light-390.jpg) | [View](screenshots/search-light-768.jpg) | [View](screenshots/search-light-1440.jpg) |
| Search, dark | [View](screenshots/search-dark-390.jpg) | [View](screenshots/search-dark-768.jpg) | [View](screenshots/search-dark-1440.jpg) |
| Review, light | [View](screenshots/review-light-390.jpg) | [View](screenshots/review-light-768.jpg) | [View](screenshots/review-light-1440.jpg) |
| Review, dark | [View](screenshots/review-dark-390.jpg) | [View](screenshots/review-dark-768.jpg) | [View](screenshots/review-dark-1440.jpg) |
| Bookings, light | [View](screenshots/bookings-light-390.jpg) | [View](screenshots/bookings-light-768.jpg) | [View](screenshots/bookings-light-1440.jpg) |
| Bookings, dark | [View](screenshots/bookings-dark-390.jpg) | [View](screenshots/bookings-dark-768.jpg) | [View](screenshots/bookings-dark-1440.jpg) |

Use the reference URL for the screen and theme, set the browser content viewport to the stated width, allow enough height for the entire application, and wait for fonts, page entry and theme transitions to settle. Capture the application from its top-left corner to its measured bottom edge. No booking is created or cancelled for these references. The review screen selects The Studio for 19 October 2026, 13:00-14:00. The bookings screen retains the two original seeded reservations.

The 1440 px captures were taken through normal preview navigation; the smaller captures use the wrapper's reference mode. Both use the same approved fragment and seed values. The reference-mode tablet review is taller than search/bookings because the prototype populates review dynamically. Hidden pages reserve space in the shared grid, including on mobile. Preserve this evidence; do not treat screenshot heights as fixed-height production requirements.

## Limitations and future verification

- The prototype uses local demo state. It has no production API, authentication, database or deployment integration.
- External fonts are not vendored or revision-pinned. Native date/time controls and font rasterization can vary by browser, locale and operating system. The reported browser user agent does not expose an exact patch/build identifier.
- The original source includes overridden CSS and preview-specific labels. Read the final cascade and the wiki specification when extracting production components.
- The prototype has not passed a WCAG 2.2 AA audit. Loading, empty, error, timeout and concurrent-conflict designs need visual review where complete states are not demonstrated. Static captures do not validate motion, keyboard operation, 200% zoom or System preference changes.
- Browser renderer restarts were needed during interactive capture. The final references were inspected after successful rendering; this archive does not claim browser stability testing.

Implementation should compare each feature against these references and use a pinned environment for reviewed visual tests, following [Playwright guidance](https://playwright.dev/docs/test-snapshots). Test motion separately. Keep backend integration and CI/CD in the vertical-slice workflow. No visual test gate is installed by this archive.

## Change control

Keep v1 immutable. Future deliberate visual revisions need before-and-after evidence, Saad's approval, independent PR review and a new baseline version. Production code may be refactored while preserving the approved appearance and behaviour. Never regenerate reference images automatically to make failing checks pass.

## Verify the source

From the repository root in PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 docs/design/baselines/v1/approved-prototype.html
```

Compare with the hash above and in the manifest. Verify the remaining listed hashes before using the archive as implementation evidence.
