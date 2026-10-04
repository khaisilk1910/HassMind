---
name: home-security-monitor
description: Rà soát cửa, contact sensor, motion, presence và ngữ cảnh an ninh nhà
  thông minh để phát hiện tình huống cần chú ý.
---

# Objective
Đưa ra cảnh báo dựa trên nhiều tín hiệu thay vì một sensor đơn lẻ.

# Workflow
1. Đọc trạng thái cửa/contact, motion/presence và chế độ nhà nếu có.
2. Kiểm tra event gần nhất khi trạng thái bất thường hoặc mâu thuẫn.
3. Ưu tiên tình huống có bằng chứng rõ: cửa mở kéo dài, motion khi dự kiến vắng, sensor mất kết nối.
4. Chỉ đề xuất action mà policy cho phép; ưu tiên thông báo hơn hành động mạnh.

# Safety rules
Không tự điều khiển lock/alarm/cover nếu policy không cho phép. Không khẳng định có xâm nhập chỉ từ motion sensor.
