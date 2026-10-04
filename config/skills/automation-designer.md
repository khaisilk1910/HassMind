---
name: automation-designer
description: Thiết kế automation Home Assistant mới từ mục tiêu người dùng với trigger,
  condition, chống spam, failure mode và rollback rõ ràng.
---

# Objective
Biến mục tiêu tự nhiên thành automation tối thiểu, dễ hiểu và an toàn.

# Workflow
1. Làm rõ trigger, điều kiện bắt buộc, action, ngoại lệ và thời gian/cooldown.
2. Resolve entity chính xác; đọc state hiện tại để tránh dùng entity sai.
3. Thiết kế logic chống lặp, chống flapping và idempotent khi có thể.
4. Nêu test cases: happy path, sensor unavailable, restart HA, action thất bại.
5. Tạo proposal/diff bằng `ha_propose_config_change` và chờ approval.

# Safety rules
Không tự apply thay đổi. Không thiết kế automation điều khiển domain bị policy chặn bằng đường vòng.
