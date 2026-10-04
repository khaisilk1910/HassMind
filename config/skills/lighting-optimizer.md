---
name: lighting-optimizer
description: Tối ưu chiếu sáng Home Assistant theo lux, thời gian, hiện diện, scene
  và trạng thái đèn để tăng tiện nghi và giảm điện năng.
---

# Objective
Đưa ánh sáng về mức phù hợp với bối cảnh mà không tạo nhấp nháy hoặc lệnh dư thừa.

# Workflow
1. Đọc light state, brightness/color hiện tại cùng lux và presence nếu có.
2. Xác định mục tiêu từ yêu cầu người dùng, scene, thời gian và mức sáng môi trường.
3. Tránh gửi lệnh nếu thiết bị đã gần trạng thái mong muốn.
4. Khi đề xuất automation, thêm hysteresis/cooldown phù hợp để chống bật tắt liên tục.

# Safety rules
Không tự thay đổi scene/automation lưu trữ nếu chưa qua approval. Không coi thời gian đơn thuần là bằng chứng có người trong phòng.
