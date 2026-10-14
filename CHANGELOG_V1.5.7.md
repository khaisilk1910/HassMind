# HassMind v1.5.7 — Chat timestamps, daily retention & paged admin security log

## Chat
- Timestamp displayed below **each** user and assistant message (dd/mm/yyyy HH:mm:ss, timezone offset).
- Chat history served by `/api/messages/{session_id}` now carries `created_at`, while the agent's internal context shape remains backward-compatible.
- Prior implementation retained SQLite `messages` indefinitely. From v1.5.7, only the **current local calendar day** in the configured `TIMEZONE` is kept; yesterday's chat messages are excluded from all history/context queries immediately after midnight.
- Existing previous-day rows are deleted when the application starts, and a background task purges at midnight every day. This is **not** a rolling 24-hour retention period.
- Prior-day device focus is reset as well. Browser tabs left open automatically refresh their chat display after a date change.
- Does not automatically delete independent audit logs, approvals, or runtime log files.

## Settings → Admin security audit
- Admin audit log is paginated on the server, newest first, with **20 events per page** by default.
- User-selectable page sizes: 10 / 20 / 50 / 100.
- Previous/Next pagination, page count and total event count, bounded scrolling height.
- API `/api/auth/audit?page=1&page_size=20` returns `{items,page,page_size,total,pages}`.
- Legacy API `/api/auth/audit?limit=50` continues returning an array.

## Verification
- `python -m compileall -q app`: passed.
- `node --test tests/test_knowledge_ui.js`: 35/35 passed, including two new UI tests.
- `python -m pytest -q --ignore=tests/test_conditional_scheduler_notify.py --ignore=tests/test_knowledge_routing.py --ignore=tests/test_skill_dry_run.py`: 232 passed, 12 subtests passed.
- The three excluded test files could not be collected because `openai` was not installed in this verification environment; full runtime/Docker/HA integration was not exercised.
