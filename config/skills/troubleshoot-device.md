---
name: troubleshoot-device
description: Chẩn đoán một thiết bị Home Assistant cụ thể dựa trên state, attributes,
  event, history và integration liên quan.
---

# Objective
Khoanh vùng lỗi của một entity/thiết bị cụ thể với số tool call tối thiểu.

# Workflow
1. Resolve đúng entity nếu tên người dùng chưa rõ.
2. Đọc state, attributes, availability và `last_changed`.
3. Chỉ dùng event/history khi cần biết lỗi bắt đầu khi nào hoặc có flapping hay không.
4. Kiểm tra integration liên quan khi nhiều entity của cùng thiết bị đều lỗi.
5. Đề xuất bước khắc phục từ ít phá hoại đến nhiều tác động.

# Safety rules
Không reset/restart thiết bị nếu chưa có tool và policy riêng cho phép. Không coi `unavailable` là bằng chứng chắc chắn của hỏng phần cứng.
