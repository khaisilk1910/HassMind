# QA report — HassMind v1.5.8 Admin redesign

## Functional regression
- `node --test tests/test_knowledge_ui.js`: 35/35 passed.
- `python -m pytest -q --ignore=tests/test_conditional_scheduler_notify.py --ignore=tests/test_knowledge_routing.py --ignore=tests/test_skill_dry_run.py`: 236 passed, 12 subtests passed.
- `python -m compileall -q app`: passed.
- `node --check static/app.js`: passed.

## Visual/browser QA
- Headless Chromium screenshots of overview, settings and security-audit views, desktop and mobile.
- Headless Chromium interaction: switch all three Settings categories at 1440px and 390px, check active button, visible panel and `aria-pressed` value: passed.
- Horizontal overflow after category changes: 0px at both tested widths.
- `prefers-reduced-motion` CSS rule present.
- Screenshots show SAMPLE data, not live service status.

## Known limitation
The three excluded Python test modules require `openai`, which is not installed in the test environment. Full end-to-end container/HA testing remains to be done in deployment.
