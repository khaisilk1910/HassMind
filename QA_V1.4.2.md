# QA v1.4.2 — Quiet Actionable Notifications

## Scope
- Conditional Scheduler/Event notification suppression.
- Exact silent-token compatibility.
- Natural-language no-op fallback.
- Guardrails preventing suppression of actions/errors/warnings.
- `always` mode compatibility.
- Web Admin wording/version surfaces.

## Automated checks
- Python: **191 passed + 12 subtests passed** (`pytest -q`).
- JavaScript UI: **31/31 passed** (`node --test tests/test_knowledge_ui.js`).
- `python -m compileall`: PASS.
- `node --check static/app.js`: PASS.
- Built-in skill validation: **22/22 valid**, 0 warnings.
- YAML parse: **6/6** Compose/Stack/Portainer/MCP files PASS.
- Static HTML ID uniqueness: PASS, **184 IDs / 0 duplicates**.

## Notification-specific coverage
- Exact `__HASSMIND_NO_NOTIFY__` result remains silent.
- In actionable mode, `✅ Không phát hiện thiết bị nào cần xử lý.` is suppressed and transport is not called.
- A no-op-looking result that also reports `unavailable` / `cần kiểm tra` is still delivered.
- The same no-op sentence is still delivered in `always` mode.
- Conditional prompt no longer contains the conflicting natural-language no-op example.
- Existing malformed-result cleanup and notification routing tests remain green.

## Environment note
The QA runtime does not provide production MCP packages and its OpenAI namespace does not expose `AsyncOpenAI`. Minimal import-only stubs were placed outside the source tree under `/mnt/data/hassmind_qa_stubs` for the test run. They are not included in the release archive. No live Home Assistant action or notification was executed during QA.
