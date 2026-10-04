# HassMind v1.2.9 — QA report

Date: 2026-10-04

## Scope

Regression review after polishing the confirmed-working v1.2.8 Zalo rich-text transport for mobile readability.

## Zalo formatter / transport

- Main heading still compiles to `f_18` + `b`: PASS.
- `###` and inline Markdown/Zalo styles remain supported: PASS.
- unordered/ordered lists still compile to `lst_1` / `lst_2`: PASS.
- nested 1..8-space indentation still compiles to `ind_$` + bounded `indentSize`: PASS.
- UTF-16 offset regression with emoji/variation selector: PASS.
- plain list label auto-bold: PASS.
- long non-list sentence ending in `:` is not incorrectly auto-bolded: PASS.
- green/orange/red conservative auto-status coloring: PASS.
- explicit model color overrides auto color: PASS.
- duplicate/overlapping identical style spans are merged: PASS.
- `/api/sendMessageByAccount` still receives plain `msg` + `styles[]`: PASS.
- HTTP 400/422 style rejection still falls back once to clean plain text: PASS.

## Existing regression suite

- Home Assistant action target/data tests: PASS.
- TTS no-registry fast path tests: PASS.
- WebSocket frame ceiling tests: PASS.
- HA state cache tests: PASS.
- Custom Integration typed action tests: PASS.

## Automated checks

- Python `compileall`: PASS.
- Unit test discovery: 34/34 PASS.
- `setup.sh` syntax (`sh -n`): PASS.
- JavaScript syntax (`node --check`): PASS.
- YAML parse for deployment/config YAML files: PASS.
- ZIP integrity: PASS.
- Version synchronized to `1.2.9`: PASS.

## End-to-end evidence

The user-provided Zalo screenshot confirmed that the v1.2.8 `msg + styles[]` transport renders headings, bold text, bullets and nested bullets correctly in the real Zalo client. v1.2.9 keeps that transport contract and only improves generation/style enrichment before send.
