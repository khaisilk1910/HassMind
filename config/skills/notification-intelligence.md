---
name: notification-intelligence
description: Quyết định khi nào cần gửi thông báo và tạo nội dung ngắn gọn, đúng format
  cho Home Assistant mobile hoặc Zalo.
---

# Objective
Chỉ thông báo khi có giá trị và giữ tin nhắn ngắn, rõ, không rò markdown thừa.

# Workflow
1. Phân biệt kết quả bình thường, actionable, cảnh báo và lỗi transport.
2. Với chế độ actionable, không gửi nếu không có hành động/cảnh báo hữu ích.
3. Mobile: dùng text thuần ngắn, emoji vừa phải, không để ký tự Markdown `*`, `_`, heading.
4. Zalo: dùng định dạng mà Zalo transport hỗ trợ; ưu tiên đoạn ngắn, bullet rõ và tránh markup không được renderer nhận dạng.
5. Không lặp lại toàn bộ log/tool output trong notification.

# Safety rules
Không gửi secret, token, thread credential hoặc dữ liệu debug nhạy cảm. Nếu transport lỗi, giữ nguyên kết quả tác vụ và báo lỗi gửi riêng.
