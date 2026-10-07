# QA v1.4.1 — Advanced Scheduler

## Scope
- Weekly weekday scheduling.
- Repeating time windows, including overnight windows.
- Daily, continuous interval and one-shot compatibility.
- Scheduler Web Admin editor, API validation and agent tool schema.
- Bedroom Climate Comfort scheduling guidance.

## Automated checks
- Python: **187 passed + 12 subtests passed** (`pytest -q`).
- JavaScript UI: **31/31 passed** (`node --test tests/test_knowledge_ui.js`).
- `python -m compileall`: PASS.
- `node --check static/app.js`: PASS.
- Built-in skill validation: **22/22 valid**, 0 warnings.
- YAML parse: **6/6** Compose/Stack/Portainer/MCP files PASS.
- Static HTML ID uniqueness: PASS, **184 IDs / 0 duplicates**.

## Scheduler-specific coverage
- Selected weekday next-run calculation.
- Same-day weekly slot already passed.
- Same-day time window interval calculation.
- Overnight window continuation from the previous start day.
- End time treated as stop boundary.
- Empty weekday selection and equal start/end rejected.
- Future one-shot parsing and past one-shot rejection.
- One-shot auto-disable before prompt execution.
- API accepts `weekly` and overnight `window`, persists values, rejects invalid empty-weekday window.
- UI serializes one overnight window into a single Scheduler job.
- Legacy `daily` and `interval` edit/save/runtime tests remain green.

## Environment note
The QA runtime does not provide production MCP packages and its OpenAI namespace does not expose `AsyncOpenAI`. Minimal import-only stubs were placed outside the source tree under `/mnt/data/qa_stubs` for the full test run. They are **not included** in the release archive. No live Home Assistant action, HVAC command, fan command or notification was executed during QA.
