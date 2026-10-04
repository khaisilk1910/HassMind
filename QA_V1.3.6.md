# QA HassMind v1.3.6

## Phạm vi rà soát

- Sửa output lỗi của chế độ `Luôn gửi kết quả`, gồm đúng mẫu lỗi được báo cáo.
- Notification formatting Điện thoại/Zalo và sentinel của chế độ `actionable`.
- Event-rule `notify_mode`, SQLite migration, create/update và runtime prompt.
- Tool audit limit + scroll.
- Scheduler/Event rules collapse + pagination 20/trang + edit flow.
- Menu order và regression Knowledge/Admin hiện có.

## Kết quả

- `python -m py_compile app/*.py app/integrations/*.py`: PASS.
- `node --check static/app.js`: PASS.
- Python full suite: **158 PASS + 12 subtests PASS**.
- JavaScript UI suite: **25/25 PASS**.
- Test regression riêng xác nhận chuỗi lỗi `*(Theo đúng yêu*(Hệ thống ... đúng theo điều kiện không gửi thông báo).\*` được chuẩn hóa thành câu sạch, có emoji, và chính câu sạch được gửi + lưu.
- Test API/database xác nhận phân trang 20 mục/trang và migration `event_rules.notify_mode`.
- Test UI xác nhận Tool audit giới hạn/scroll, Scheduler/Event rules thu gọn, request `page_size=20`, Event rule load/save `notify_mode`.

## Ghi chú môi trường QA

Runner không có package `openai` và `mcp` cài sẵn và không có mạng để tải dependency. Full suite được chạy với **import-only stubs** đặt ngoài source tree cho hai package này; stub không thực hiện network call. Các test chức năng sửa đổi ở bản này không phụ thuộc OpenAI/MCP thật. Image HassMind vẫn cài dependency thật từ `requirements.txt` khi build.
