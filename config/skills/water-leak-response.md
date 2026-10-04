---
name: water-leak-response
description: Xử lý cảnh báo rò nước từ binary sensor/moisture sensor với xác minh
  trạng thái, ngữ cảnh và thông báo ưu tiên cao.
---

# Objective
Phản ứng nhanh nhưng tránh hành động phá hoại khi sensor lỗi.

# Workflow
1. Đọc leak/moisture sensor và availability.
2. Kiểm tra event gần nhất hoặc sensor liên quan nếu có dấu hiệu false positive.
3. Thông báo rõ khu vực, sensor và thời điểm.
4. Chỉ thực hiện hành động khác nếu đã có tool/policy chuyên biệt và người dùng cho phép.

# Safety rules
Không tự đóng van/điều khiển thiết bị ngoài allowlist bằng đường vòng. Nếu sensor unavailable, báo lỗi cảm biến thay vì khẳng định có hoặc không có rò nước.
