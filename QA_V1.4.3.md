# QA v1.4.3 — Strict Quiet Scheduler

## Scope
- Actionable notification suppression dựa trên tool evidence.
- Refusal/chatter suppression.
- Hallucinated-action suppression.
- Scheduler/Event stateless execution.
- Existing always-mode compatibility.
- Strict `action_only` notification mode.

## Automated checks
- Python: **198 passed + 12 subtests passed** (`pytest -q`) với import-only MCP/OpenAI stubs ngoài source tree cho môi trường QA.
- JavaScript UI: **31/31 passed** (`node --test tests/test_knowledge_ui.js`).
- Python compile: PASS.
- JavaScript syntax: PASS.

## New regression coverage
- Capability refusal không có tool evidence không gọi notification transport.
- Kết quả ngắn sau side-effect tool thành công vẫn được gửi.
- Câu `Đã tắt...` không có side-effect tool evidence bị suppress.
- Natural-language no-op vẫn silent.
- Warning quan trọng vẫn được phép gửi.
- `always` mode vẫn gửi no-op như trước.
- `action_only` suppress warning/read-only result khi chưa có side-effect thành công.
- `action_only` gửi sau side-effect thành công.
- Nếu model trả silent token sau action thật, backend fallback từ tool evidence và vẫn gửi.

## Environment note
Không có Home Assistant/Zalo production endpoint nào được gọi trong QA. Các stub chỉ phục vụ import trong test runtime và không được đóng gói vào release.
