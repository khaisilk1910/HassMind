# HassMind v1.4.3 — Strict Quiet Scheduler

## Fixed
- Sửa trường hợp Scheduler/Event rule `notify_mode=actionable` vẫn gửi các câu từ chối/capability disclaimer của model như `Tôi là một mô hình ngôn ngữ...` dù không có thao tác Home Assistant nào.
- Sửa rủi ro history drift: các lần chạy `job:<id>` / event rule trước đây dùng lại lịch sử cùng session, khiến refusal/no-op cũ có thể ảnh hưởng lần chạy sau. Scheduler/Event system run giờ được đánh giá độc lập, chỉ dùng prompt hiện tại.
- Thêm tool-evidence gating cho conditional notification. Side-effect tool thành công hoặc tool error thực tế được ghi nhận; prose không có bằng chứng action/error không còn đủ để kích hoạt push.
- Chặn cả trường hợp model tự tuyên bố `Đã tắt...` nhưng thực tế không có side-effect tool thành công.

## Conditional notification behavior
- `actionable`: có side-effect tool thành công hoặc lỗi/cảnh báo thực tế thì có thể gửi; refusal/chatter/no-op không có bằng chứng sẽ im lặng.
- `action_only`: **chỉ gửi khi backend ghi nhận ít nhất một side-effect tool thành công**. Nếu không có action thành công thì im lặng kể cả warning, tool error, thiếu dữ liệu hoặc model refusal.
- Nếu action đã thành công nhưng model nhầm trả silent token, backend tạo fallback ngắn từ tool evidence để không làm mất thông báo action thật.
- `always`: giữ nguyên hành vi và luôn gửi kết quả.

## Prompt hardening
- Runtime conditional protocol nhắc agent rằng nó đang chạy trong HassMind và có Home Assistant tools.
- Cấm dùng capability disclaimer thay cho việc gọi tool khi prompt yêu cầu kiểm tra/điều khiển Home Assistant.
- Nếu prompt gốc yêu cầu im lặng khi thiếu dữ liệu an toàn, protocol nhắc trả silent token.

## UI
- Scheduler và Event rules có thêm lựa chọn **Chỉ gửi khi có thao tác thành công**.
- Job cũ giữ nguyên `always`/`actionable`; người dùng có thể đổi riêng các job cần chính sách nghiêm ngặt sang `action_only`.

## Compatibility
- Không đổi database schema.
- Không cần migration.
- Job và Event rule hiện có giữ nguyên cấu hình.
