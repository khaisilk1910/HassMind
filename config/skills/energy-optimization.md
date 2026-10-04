---
name: energy-optimization
description: Phân tích công suất, điện năng và lịch sử tải để đề xuất tối ưu Home
  Assistant tiết kiệm điện mà không ảnh hưởng tải quan trọng.
---

# Objective
Tìm cơ hội tiết kiệm dựa trên dữ liệu đo được, không dựa trên giả định.

# Workflow
1. Đọc sensor power/energy liên quan và chọn khoảng lịch sử phù hợp.
2. Phân biệt công suất tức thời với điện năng tích lũy.
3. Tìm tải nền, thời gian hoạt động bất thường, thiết bị chạy khi không cần và cơ hội scheduling.
4. Ước lượng tác động trước khi đề xuất automation.
5. Mọi sửa automation phải qua approval.

# Safety rules
Không tự tắt tủ lạnh, mạng, thiết bị y tế/an toàn hoặc tải chưa xác định. Không ngoại suy chi phí nếu thiếu tariff.
