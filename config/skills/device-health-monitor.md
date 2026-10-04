---
name: device-health-monitor
description: Phát hiện và chẩn đoán entity unavailable, unknown, pin yếu, mất cập
  nhật hoặc trạng thái bất thường trong Home Assistant.
---

# Objective
Xác định thiết bị cần chú ý và nguyên nhân khả dĩ dựa trên bằng chứng Home Assistant.

# Workflow
1. Tìm entity `unavailable`/`unknown` và sensor pin thấp khi người dùng yêu cầu rà soát.
2. Kiểm tra `last_changed`, attributes và event/history gần nhất khi cần.
3. Nhóm lỗi theo thiết bị/area/integration để tránh báo trùng.
4. Phân biệt lỗi thiết bị với lỗi integration hoặc mất kết nối Home Assistant.
5. Đề xuất bước khắc phục ít phá hoại nhất trước.

# Safety rules
Không restart, reload hay reset thiết bị/integration nếu chưa có tool và policy cho phép. Không suy diễn lỗi phần cứng chỉ từ một trạng thái ngắn hạn.
