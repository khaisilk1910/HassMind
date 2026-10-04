---
name: air-quality-manager
description: Theo dõi CO2, PM2.5, VOC, nhiệt độ và độ ẩm để đề xuất thông gió hoặc
  điều khiển thiết bị không khí theo Home Assistant.
---

# Objective
Đánh giá chất lượng không khí từ sensor thực tế và đưa ra hành động vừa đủ.

# Workflow
1. Đọc sensor air-quality cùng availability và đơn vị đo.
2. Kiểm tra trend/history khi giá trị đột biến hoặc kéo dài.
3. Đối chiếu climate/fan/purifier state trước khi đề xuất thay đổi.
4. Chỉ gọi action nếu thiết bị và policy hỗ trợ rõ ràng.

# Safety rules
Không đưa chẩn đoán y tế. Không so sánh số đo khác đơn vị hoặc sensor chưa hiệu chuẩn như thể tương đương.
