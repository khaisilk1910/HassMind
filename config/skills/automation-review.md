---
name: automation-review
description: Rà soát automation/script Home Assistant, phát hiện logic dư thừa, xung
  đột, trigger sai và cơ hội cải tiến an toàn.
---

# Objective
Review cấu hình hiện tại và đưa ra thay đổi nhỏ, kiểm chứng được, dễ rollback.

# Workflow
1. Đọc cấu hình automation/script liên quan và xác định mục tiêu thực tế.
2. Kiểm tra trigger, condition, action, entity tồn tại, concurrency mode, cooldown/debounce và các nhánh xung đột.
3. Đối chiếu state/event/history khi cần để chứng minh vấn đề.
4. Xếp hạng đề xuất theo tác động và rủi ro.
5. Mọi thay đổi cấu hình phải dùng `ha_propose_config_change`; không ghi trực tiếp.

# Safety rules
Không tối ưu chỉ vì style. Giữ nguyên hành vi đang đúng nếu thiếu bằng chứng. Nêu rõ rollback cho thay đổi đáng kể.
