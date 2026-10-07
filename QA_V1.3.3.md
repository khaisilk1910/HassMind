# QA — HassMind 1.3.3 Scheduler reliability hotfix

Date: 2026-10-04

## Kiểm tra đã chạy

- `python3 -m compileall -q app tests`: PASS.
- Parse AST toàn bộ `app/**/*.py` và `tests/**/*.py`: PASS.
- Targeted Python tests cho message formatting, notification routing, Scheduler và Zalo transport: **32 tests PASS**.
- JavaScript UI tests `node tests/test_knowledge_ui.js`: **22/22 PASS**.
- Full Python unit suite: **145 tests PASS** trong môi trường hiện tại với import-only stubs cho `openai` và `mcp` vì container QA ngoại tuyến không có hai package runtime này. Các stub chỉ cho phép import module; không giả lập LLM/MCP network behavior.

## Regression mới

- Zalo message dài được chia trước transport; mỗi chunk mặc định không vượt 900 ký tự markup và 40 style spans.
- Rich-text visible `msg` không lộ `**` sau chunking.
- Scheduler interval `30` không còn bị nâng thành `60`; `<30` bị từ chối.
- Numeric optional argument rỗng không còn làm `ha_search_states` crash.
- Mô phỏng transport exception sau khi agent trả kết quả xác nhận `run_prompt()` vẫn trả kết quả thành công kèm cảnh báo notification, đồng thời log `system_notification_failed`.

## Giới hạn QA

- Không có Docker daemon/live Home Assistant/Zalo companion trong môi trường build này.
- Không thực hiện gửi Zalo thật; ngưỡng chunking được chọn từ telemetry trong log người dùng: payload ~855/40 và ~925/44 styles đã thành công, trong khi ~1791/91 và ~2025/114 trả HTTP 500.
- Vẫn giữ nguyên nguyên tắc không retry HTTP 5xx để tránh duplicate message trong failure không xác định.
