---
name: self-maintenance
description: Tự kiểm tra sức khỏe HassMind, Home Assistant, database, event stream
  và integration ở mức không phá hoại.
---

# Objective
Phát hiện lỗi vận hành của HassMind/HA mà không thay đổi host hoặc container.

# Workflow
1. Kiểm tra health/status/diagnostics và kết nối Home Assistant.
2. Kiểm tra database writable, background tasks, event stream và lỗi tool gần đây khi có dấu hiệu bất thường.
3. Kiểm tra integration health nếu lỗi liên quan dịch vụ ngoài.
4. Đưa ra nguyên nhân khả dĩ theo bằng chứng và bước kiểm tra tiếp theo.

# Safety rules
Không chạy shell, restart host/container, update Home Assistant hoặc tự sửa secret. Chỉ đề xuất thao tác quản trị thủ công khi cần.
