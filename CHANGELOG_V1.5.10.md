# HassMind v1.5.10 — Settings security layout hotfix

## Fixed

- **Settings > Phiên & bảo mật:** Fix cards displayed as extremely narrow vertical columns on desktop. The global `.grid` has 12 tracks, but v1.5.8 UI rules overrode `.span-6` with `grid-column:auto`; each card unintentionally occupied one track rather than six.
- Restore each security card to six grid columns at desktop widths above 1100px, and full 12 columns on smaller screens.
- Improve readability of long session user-agent / network / log-path values, with safe wrapping and single-column key-value details on small phones.
- Update cache-busting URLs for UI assets to v1.5.10, avoiding stale browser CSS after deployment.

## Scope

- Based on v1.5.9 security-hardened source. All authentication, webhook, Telegram, chat retention, audit and other backend behavior is preserved.
- No database schema, credentials or `/data` migration required.

## QA

- Targeted Python tests: 15 passed, 1 skipped.
- JavaScript tests: 35 passed.
- Chromium layout checks: widths 1600, 1440, 1200, 1100, 980, 768, 390, and 320 pixels: no horizontal overflow; cards align two-column above 1100 and stack at 1100 and narrower.
- Python compile and JavaScript syntax checks passed.
- Full Python suite did not finish within the available local execution time; production Docker/Home Assistant not exercised.
