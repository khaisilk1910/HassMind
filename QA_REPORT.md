# HassMind v1.2.8 — QA report

Date: 2026-10-04

## Scope

Regression review after moving Zalo formatting from markup-only transport to compiled zca-js `msg + styles[]` transport.

## Root-cause verification

- v1.2.7 outbound body contained only `message.msg` with visible `#`, `**`, backticks and color tags: CONFIRMED.
- The Zalo screenshot showed those delimiters literally, so the companion `/api/sendMessageByAccount` path was not parsing the markup before send: CONFIRMED from observed behavior.
- zca-js `MessageContent` supports a plain `msg` plus explicit `styles[]`: transport fix implemented.

## Rich-text compiler

- Heading `#`/`##` -> `f_18` + `b`: PASS.
- Heading `###` -> `b`: PASS.
- Heading `####`..`######` -> `f_13`: PASS.
- `**bold**`: PASS.
- `*italic*`: PASS.
- `***bold italic***`: PASS.
- `__underline__`: PASS.
- `~~strike~~`: PASS.
- Backticks -> italic compatibility behavior: PASS.
- red/orange/yellow/green tags -> official zca-js color codes: PASS.
- big/small tags -> `f_18` / `f_13`: PASS.
- unordered/ordered list -> `lst_1` / `lst_2`: PASS.
- 1..8 leading spaces / nested lists -> `ind_$` + bounded `indentSize`: PASS.
- blockquote -> italic: PASS.
- Markdown link -> URL text: PASS.
- tables/fences/FollowUp normalization retained: PASS.

## Offset correctness

- Style offsets are generated in JavaScript UTF-16 code units rather than Python code points: PASS.
- Regression test with emoji + variation selector before a bold range: PASS.

## Zalo transport

- `/api/sendMessageByAccount` now receives `message: {msg, styles}`: PASS.
- `msg` contains no supported formatting delimiters after compile: PASS.
- Explicit HTTP 400/422 rejection of `styles` retries once with compiled plain text: PASS.
- Timeout/5xx errors are not automatically retried, avoiding ambiguous duplicate sends: PASS.
- Added `zalo_rich_text_compiled` and `zalo_rich_text_styles_rejected` diagnostics: PASS.

## Existing regression suite

- Home Assistant action target/data tests: PASS.
- TTS no-registry fast path tests: PASS.
- WebSocket frame ceiling tests: PASS.
- HA state cache tests: PASS.
- Custom Integration typed action tests: PASS.

## Automated checks

- Python `compileall`: PASS.
- Unit test discovery: 29/29 PASS.
- `setup.sh` syntax (`sh -n`): PASS.
- JavaScript syntax (`node --check`): PASS.
- YAML parse for root/config YAML files: PASS.
- Version synchronized to `1.2.8`: PASS.

## Limitation

The test environment does not have the user's authenticated Zalo companion server/account, so the final visual rendering in the real Zalo client cannot be end-to-end asserted here. The outbound payload is now aligned with zca-js MessageContent's explicit `styles[]` contract and includes a safe plain-text fallback for older companion validation schemas.
