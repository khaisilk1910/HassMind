---
name: battery-maintenance
description: Theo dõi pin sensor, remote và thiết bị Home Assistant, ưu tiên thiết
  bị sắp hết pin hoặc có dấu hiệu mất kết nối.
---

# Objective
Tạo danh sách bảo trì pin có ưu tiên thay vì cảnh báo dàn trải.

# Workflow
1. Tìm battery sensor và trạng thái thiết bị liên quan.
2. Nhóm theo thiết bị/area, loại bỏ duplicate sensor.
3. Ưu tiên pin rất thấp, pin giảm nhanh, hoặc thiết bị quan trọng có dấu hiệu unavailable.
4. Nếu có lịch sử, dùng trend để phân biệt mức thấp ổn định với tụt pin bất thường.

# Safety rules
Không giả định ngưỡng pin chung phù hợp cho mọi thiết bị; dùng thuộc tính/device context khi có.
