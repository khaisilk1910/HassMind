---
name: incident-diagnosis
description: Chẩn đoán sự cố Home Assistant nhiều thành phần bằng tương quan state,
  event, log, tool audit và integration health.
---

# Objective
Tìm nguyên nhân gốc thay vì xử lý riêng từng triệu chứng.

# Workflow
1. Xác định mốc thời gian, phạm vi entity/integration và triệu chứng chính.
2. Đọc trạng thái hiện tại, event gần mốc lỗi, Tool audit và runtime logs liên quan.
3. Kiểm tra integration health nếu nhiều entity cùng nguồn lỗi.
4. Xếp giả thuyết theo bằng chứng; nêu dữ liệu còn thiếu.
5. Đề xuất bước xác minh ít rủi ro trước khi thay đổi cấu hình.

# Safety rules
Không khẳng định root cause khi chỉ có tương quan. Không restart/reload hàng loạt để thử nếu chưa có policy và xác nhận phù hợp.
