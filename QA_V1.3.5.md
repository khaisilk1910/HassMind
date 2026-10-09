# QA HassMind v1.3.5

## Phạm vi

- Conditional Scheduler notifications (`notify_mode=actionable`).
- Sentinel suppression: không gọi transport Điện thoại/Zalo khi agent trả kết quả im lặng chính xác.
- Migration SQLite cho job cũ (`notify_mode=always`).
- Tạo/sửa Scheduler qua API và Web Admin.
- `schedule_propose` tương thích chế độ notification mới.
- Regression cho notification routing, Zalo rich text, Knowledge, timezone và các test hiện có.

## Kết quả

- `python -m compileall`: PASS.
- Python unit/integration tests: **148 PASS**.
- JavaScript UI tests: **23/23 PASS**.
- Test riêng xác nhận sentinel chính xác không gọi `send_notification`; phản hồi bình thường vẫn gửi.
- Test Scheduler xác nhận prompt chỉ được bổ sung protocol nội bộ khi `notify_mode=actionable`.
- Test UI xác nhận trường **Khi nào gửi** được load khi sửa job và được lưu lại qua PUT.

## Ghi chú môi trường QA

Runner hiện tại không có package `openai` và `mcp` từ mạng ngoài, nên hai module này được cung cấp import-only stubs trong lúc chạy test. Các test không gọi OpenAI/MCP thật. Image HassMind vẫn cài dependency thật từ `requirements.txt` khi build.
