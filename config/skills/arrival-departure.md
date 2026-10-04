---
name: arrival-departure
description: Xử lý ngữ cảnh về nhà/rời nhà dựa trên person, device tracker, presence
  và trạng thái nhà để tránh automation kích hoạt nhầm.
---

# Objective
Tạo hành vi arrival/departure ổn định, chống false positive từ tracker.

# Workflow
1. Đọc person/device_tracker/presence liên quan và trạng thái nhà.
2. Dùng nhiều tín hiệu hoặc debounce khi có tracker không ổn định.
3. Arrival: chỉ bật thiết bị thực sự cần theo thời gian/area/ngữ cảnh.
4. Departure: xác nhận không còn người trước khi tắt thiết bị không cần thiết.
5. Nếu thiết kế automation, xử lý restart HA và trạng thái unknown/unavailable.

# Safety rules
Không tắt tải quan trọng khi departure chưa chắc chắn. Không dùng một tracker chập chờn làm bằng chứng duy nhất.
