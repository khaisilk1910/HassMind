# QA HassMind v1.5.12 — Zalo photo notes

## Automated tests

- Python notes, Zalo image ingress/egress, message formatting, security regression:
  **53 passed, 1 skipped** (missing optional OpenAI/MCP dependency in local environment).
- `node --test tests/test_knowledge_ui.js`: **35 passed**, 0 failed.
- Python module syntax: `python -m compileall -q app` passed.
- Exact production `_process_zalo_message` function was extracted with AST and
  exercised in tests despite unavailable optional production packages.
- New tests cover multiple webhook attachment shapes, image-first followed by
  command, text-first followed by photo, photo + caption, recall and outbound
  signed photo URLs, transport payload, 10-minute HMAC expiry, duplicate event
  filtering, allowlist enforcement, invalid media URLs, and empty upload results.

## Not verified

- Real `zalo-bot-server` `/api/sendMessageByAccount` file-attachment capability,
  actual Zalo photo download permission and Zalo app photo preview.
- Docker/Portainer live deployment on the user's host, Home Assistant, and
  TLS/reverse-proxy behavior with the selected `ZALO_MEDIA_BASE_URL`.
- Optional packages (OpenAI and MCP) were unavailable for complete application
  startup and whole-repository integration test in this QA container.

## Deployment check

Back up `/data/hassmind.db`, `/data/note_images`, and `/data/secrets` before
upgrade. Preserve `/data` volume. Set the Integration > Zalo Bot Server >
URL HassMind để Zalo tải ảnh ghi chú to an address **reachable from the companion**.
Ensure the Zalo webhook secret, allowed thread list, and send/reply policies are
configured. Avoid `*` in allowed thread list for private notes.
