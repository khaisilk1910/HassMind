---
name: night-mode
description: Điều phối ngữ cảnh ban đêm cho đèn, media, điều hòa và thông báo theo
  hiện diện, thời gian và trạng thái thực tế.
---

# Objective
Giảm làm phiền ban đêm trong khi vẫn giữ an toàn và tiện nghi.

# Workflow
1. Xác định nhà/phòng đang ở trạng thái ban đêm dựa trên yêu cầu, helper hoặc thời gian đã cấu hình.
2. Đọc trạng thái đèn/media/climate liên quan và presence nếu cần.
3. Ưu tiên giảm brightness/âm lượng hoặc giữ nguyên thiết bị đang cần thiết thay vì tắt hàng loạt.
4. Với automation, thêm ngoại lệ cho occupancy, manual override và sensor lỗi.

# Safety rules
Không tự tắt thiết bị an toàn/mạng. Không suy ra mọi người đã ngủ chỉ từ giờ hiện tại.
