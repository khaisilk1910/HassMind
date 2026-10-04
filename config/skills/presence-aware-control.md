---
name: presence-aware-control
description: Điều khiển đèn, quạt và thiết bị theo hiện diện, occupancy, trạng thái
  phòng và ngữ cảnh sử dụng thực tế.
---

# Objective
Điều khiển thiết bị theo hiện diện mà không tắt/bật nhầm khi dữ liệu cảm biến chưa chắc chắn.

# Required context
Xác định area, entity cần điều khiển, sensor presence/motion/occupancy liên quan và trạng thái hiện tại.

# Workflow
1. Resolve area/entity bằng Knowledge nếu cần.
2. Đọc trạng thái realtime của thiết bị và sensor hiện diện.
3. Kiểm tra `unknown`, `unavailable`, độ trễ và tín hiệu mâu thuẫn trước khi hành động.
4. Chỉ gửi service khi trạng thái hiện tại khác mục tiêu.
5. Nếu nhiều người/sensor có thể ảnh hưởng, ưu tiên an toàn và tránh tắt thiết bị khi occupancy chưa chắc chắn.

# Safety rules
- Không suy đoán vắng người chỉ từ một sensor lỗi hoặc stale.
- Không tắt tải an toàn/thiết bị quan trọng theo heuristic.
- Thay đổi automation phải qua proposal/approval.
