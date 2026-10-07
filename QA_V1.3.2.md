# QA — HassMind 1.3.2 notification/editing review

Kiểm thử ngày 04/10/2026. Source đầu vào: `hassmind-v1.3.1-knowledge-reviewed.zip`.

## Kết quả tổng hợp

- **141 Python tests PASS**, 0 fail/error trong lượt tổng hợp cuối (`pytest -q`).
- **22 JavaScript tests PASS** bằng `node --test tests/test_knowledge_ui.js`.
- `python -m py_compile app/*.py app/integrations/*.py`: PASS.
- `node --check static/app.js`: PASS.
- `node --check static/login.js`: PASS.

## Các regression test mới

- Mobile notification loại bỏ Markdown thô và giữ cấu trúc dễ đọc bằng emoji/bullet.
- Action buttons của Home Assistant mobile notification vẫn được truyền nguyên vẹn cho Approval.
- Zalo notification dùng `ZaloClient.send_message` và rich-text compiler hiện có; test xác nhận outbound body là `message.msg + styles[]` và không còn `**` trong `msg`.
- Resolve Zalo target đúng thứ tự explicit thread → default notification thread → Allowed thread ID; không dùng wildcard `*`.
- Notification preference của Approvals persist đúng trong SQLite.
- Scheduler create/edit persist `notify_channel`/`zalo_thread_id`, giữ enabled state và tính lại `next_run` khi sửa lịch của job đang bật.
- Event rule create/edit persist kênh thông báo và giữ enabled state.
- Migration DB cũ tự thêm `notify_channel`, `zalo_thread_id` và bảng `notification_preferences`.
- Review queue trả tối đa 4 proposal `stale`.
- UI có vùng cuộn Review changes, đủ selector/thread input cho Approvals/Scheduler/Event rules/Knowledge, nút Sửa cho Scheduler/Event rules và gọi đúng API `PUT`.
- API round-trip xác nhận save/read Approval notification preference và create/edit Scheduler/Event rules.
- Toàn bộ regression Knowledge v1.3.1 vẫn PASS, gồm conflict detail, stale protection, dry-run gate, transactional apply/rollback và Re-index warning không blocking.

## Ghi chú môi trường QA

Môi trường kiểm thử hiện tại không cài package `openai` và `mcp`. Lượt test tổng hợp dùng import-only stubs cho đúng hai package này để import `app.agent`/`app.mcp_client`; không stub logic notification, Zalo formatter/transport, SQLite migration, Scheduler/Event rules, Knowledge, FastAPI/TestClient, auth, transaction hay JavaScript UI.

Chưa kết nối Home Assistant/Zalo Server thật trong QA container. Sau deploy nên kiểm tra một notification mobile, một notification Zalo, sửa một Scheduler job và một Event rule trên Web Admin trước khi bật automation production.
