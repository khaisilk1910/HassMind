---
name: smart-home-router
description: Phân loại yêu cầu Home Assistant và chọn workflow phù hợp cho trạng thái,
  điều khiển, chẩn đoán, automation, knowledge hoặc integration.
---

# Objective
Chọn đường xử lý ngắn nhất và an toàn nhất trước khi gọi nhiều tool.

# Workflow
1. Xác định ý định: đọc trạng thái, điều khiển, chẩn đoán, automation/script, Knowledge, báo cáo hay integration.
2. Nếu tên thiết bị mơ hồ, dùng `knowledge_resolve`; nếu đã có `entity_id` chính xác thì ưu tiên state tool trực tiếp.
3. Với trạng thái hiện tại của nhiều entity, ưu tiên `ha_search_states` hoặc `ha_get_states` thay vì gọi lặp từng entity.
4. Đọc skill chuyên dụng nếu có trước khi thực hiện workflow phức tạp.
5. Chỉ gọi action tool khi mục tiêu và đối tượng đã rõ.

# Safety rules
- Không biến kết quả fuzzy thành xác nhận điều khiển.
- Không dùng Knowledge làm nguồn trạng thái realtime.
- Không tìm đường vòng qua tool chung khi đã có typed adapter hoặc policy riêng.

# Response format
Trả lời trực tiếp kết quả; chỉ nêu tool/chi tiết kỹ thuật khi cần giải thích hoặc chẩn đoán.
