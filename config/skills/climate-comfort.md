---
name: climate-comfort
description: Điều phối điều hòa, quạt và thông gió theo nhiệt độ, độ ẩm, hiện diện
  và trạng thái HVAC để tối ưu tiện nghi.
---

# Objective
Đạt mức tiện nghi hợp lý với ít thay đổi thiết bị nhất.

# Workflow
1. Đọc temperature, humidity, climate/fan state và occupancy liên quan.
2. Phân biệt nhiệt độ đo được với setpoint HVAC.
3. Ưu tiên thay đổi nhỏ, tránh thay đổi mode/setpoint liên tục.
4. Nếu dữ liệu môi trường lỗi hoặc stale, báo rõ và không tự điều chỉnh mạnh.

# Safety rules
Không tắt HVAC phục vụ mục đích an toàn hoặc môi trường đặc biệt nếu chưa xác định rõ. Mọi automation mới/sửa phải qua proposal/approval.
