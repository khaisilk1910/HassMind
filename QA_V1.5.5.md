# QA v1.5.5

## Tự động

- `python -m compileall -q app` — đạt.
- `PYTHONPATH=. python -m pytest -q tests/test_session_followups.py` — 11 passed.
- `PYTHONPATH=. python -m pytest -q --continue-on-collection-errors` — 209 passed, 12 subtests passed; 16 collection/setup errors vì môi trường không có package `openai` (và `mcp` trong bộ tích hợp), không thể cài package qua mạng từ môi trường này.
- `node --check static/app.js` — đạt.
- `node --test tests/test_knowledge_ui.js` — 33 passed.

## Phạm vi test phiên

- Đọc state realtime lần sau, lọc đúng entity; không rò rỉ entity thuộc Device khác.
- Bật/tắt là intent riêng: không điều khiển bằng nhánh đọc theo ngữ cảnh.
- Ngữ cảnh tách biệt theo `session_id` và `source`; hệ thống Scheduler không có focus.
- Đổi chủ đề, hết TTL và Device đã gỡ Knowledge thì không kế thừa focus.
- Tin nhắn đồng thời cùng phiên được xếp tuần tự, AI phân tích câu hỏi đánh giá.

## Giới hạn xác nhận

- Chưa kiểm thử tích hợp OpenAI/MCP đầy đủ hay triển khai trong Docker Swarm thật.
- Việc người dùng hỏi điều khiển bằng đại từ sẽ do AI và policy hiện tại xử lý; nếu không đủ rõ phải hỏi lại, tuyệt đối không coi focus như cấp quyền điều khiển.
