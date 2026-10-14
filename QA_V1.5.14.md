# Kiểm thử HassMind v1.5.14 (mô phỏng/offline)

- 61 Python passed, 1 skipped: `test_zalo_notes.py`, `test_notes.py`, `test_zalo_transport.py`, `test_security_hardening.py`, `test_message_format.py`.
- 35 Node.js tests passed: `test_knowledge_ui.js` phía HassMind.
- 7 Node.js tests passed: `zalo-bot-server/tests/incomingPhotoCache.test.js`.
- Kiểm tra cú pháp Python và Node: passed.
- Luồng đã xác nhận: nội dung trước → hỏi và chờ ảnh; nhận ảnh relay vào ghi chú; 60 giây tự lưu chỉ có chữ; ảnh tải lỗi vẫn giữ nội dung; nhiều ảnh tối đa 5; không tải ảnh gửi trước nội dung; chống webhook trùng; tách thread; tự gửi thông báo sau khi chờ hết hạn.

**Chưa kiểm thử:** full Node test suite Zalo Server (môi trường build này không có npm dependencies), proxy thực và kết nối CDN Zalo, Docker/HA/Zalo thực tế. Chỉ coi kết quả gửi/nhận ảnh là được xác nhận sau khi chạy thử với tài khoản Zalo thật.
