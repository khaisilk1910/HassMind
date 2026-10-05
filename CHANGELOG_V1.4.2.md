# HassMind v1.4.2 — Quiet Actionable Notifications

## Fixed
- Sửa lỗi Scheduler/Event rule ở `notify_mode=actionable` vẫn gửi các câu no-op như `✅ Không phát hiện thiết bị nào cần xử lý.`.
- Loại bỏ chỉ dẫn mâu thuẫn trong prompt conditional: trước đây prompt vừa yêu cầu silent token vừa nối contract yêu cầu trả một câu tự nhiên khi không có gì cần xử lý.
- Thêm fallback phía server để chỉ trong chế độ `actionable`, các kết quả no-op rõ ràng được chặn trước transport nếu model không tuân thủ silent token.

## Safety of suppression
- Fallback không chặn thông báo nếu kết quả có action đã thực hiện.
- Không chặn khi có lỗi/cảnh báo, `unavailable`, `unknown`, mất kết nối, cần kiểm tra, chưa xác nhận, bất thường, rất nóng/quá nóng/quá lạnh hoặc các tín hiệu quan trọng tương tự.
- `notify_mode=always` không thay đổi hành vi và vẫn gửi kết quả no-op.
- Silent token `__HASSMIND_NO_NOTIFY__` vẫn được hỗ trợ như trước.

## UI
- Đổi nhãn `actionable` thành **Chỉ gửi khi có thao tác/lỗi cần báo** cho Scheduler và Event rules.
- Hint giải thích rõ: không có action/lỗi/cảnh báo thì không gửi thông báo.

## Compatibility
- Không đổi schema database.
- Không cần migration.
- Job/Event rule hiện có giữ nguyên `notify_mode` đã lưu.
- Để nhận hành vi im lặng, job/rule phải dùng `notify_mode=actionable`; `always` cố ý vẫn gửi mọi kết quả.
