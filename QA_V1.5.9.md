# HassMind v1.5.9 - Security verification

## Source reviewed

Baseline: HassMind v1.5.8 Modern Admin UI. Review covered the HTTP admin and API boundary, cookie/session/CSRF mechanisms, Telegram/Zalo ingress, dynamic integrations, rate limiting, secrets on disk, Docker startup, and user-facing configuration.

## Results (local environment)

- Python: `python -m pytest -q --ignore=tests/test_conditional_scheduler_notify.py --ignore=tests/test_knowledge_routing.py --ignore=tests/test_skill_dry_run.py`: **243 passed, 1 skipped, 12 subtests passed**.
- JavaScript: `node --test tests/test_knowledge_ui.js`: **35 passed, 0 failed**.
- Python compile check `python -m compileall -q app`: passed.
- JavaScript syntax `node --check static/app.js`: passed.
- HTTP integration smoke (TestClient, stubs only for missing OpenAI/MCP imports, isolated test database): **11 passed**. Covered invalid Host (400), cross-origin mutation (403), oversized request (413), wrong/correct login, cookie-backed session, CSRF protection and logout.
- Security regression tests cover fail-closed Telegram permissions including group sender checks, timestamp freshness, host allowlist, Origin protection, bounded authentication work, rate-limiter bookkeeping, webhook throttling, and atomic secret replacement against symlinks.

## Unverified / deployment-specific

- A full pytest collection failed in **3 test modules** because the local environment lacks the third-party `openai` dependency. The optional HTTP-security test in the primary suite skipped for missing OpenAI/MCP SDKs; an independent TestClient smoke exercised the actual middleware with dependency import stubs.
- No live Telegram, Zalo, Home Assistant, MCP service, Docker or reverse proxy end-to-end tests were executed.
- No external CVE audit of resolved dependency/container versions and no production penetration test were executed.
- TLS, firewall, reverse-proxy trust rules, credential rotation, backups and secrets permissions require operator validation.

## Important behavior change

Telegram now denies all messages unless `TELEGRAM_ALLOWED_CHAT_IDS` is explicitly populated. For group/supergroup chats, `TELEGRAM_ALLOWED_USER_IDS` must also include the sender. If using an admin-facing custom FQDN, explicitly populate `ADMIN_ALLOWED_HOSTS` with that hostname. Retain `/data` volume during container upgrade.
