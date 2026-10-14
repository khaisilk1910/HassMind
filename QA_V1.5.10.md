# QA — HassMind v1.5.10

## Regression addressed

At viewports above 1100px, Settings > Phiên & bảo mật previously set `grid-column:auto` on cards inside a 12-column grid. This produced two one-track-width panels, severe text wrapping and broken layout.

Changed CSS:
- `.settings-security-grid>.card { grid-column:span 6 }` for desktop.
- Existing `@media(max-width:1100px)` retains `grid-column:span 12` for each card.
- Long values wrap within their own cards, with narrow key-value rows stacked on screens at or below 700px.

## Test results

- `python -m pytest -q tests/test_admin_ui_refresh.py tests/test_chat_retention_and_auth_audit.py tests/test_security_hardening.py`: 15 passed, 1 skipped.
- `node --test tests/test_knowledge_ui.js`: 35 passed.
- `python -m compileall -q app`, `node --check static/app.js`, `node --check static/login.js`: passed.
- Chromium, synthetic Settings data, widths 1600, 1440, 1200, 1100, 980, 768, 390 and 320: verified card widths at least 280px, no horizontal overflow and proper desktop/mobile alignment.
- Full existing Python test suite exceeded local execution time, so it is not reported as passed.

## Not verified

- Live admin data, Docker production deployment, network setup and Home Assistant integrations. Upgrade by rebuilding container from the archive, while retaining the persistent `/data` volume. Hard-refresh browser to discard old CSS if needed.
