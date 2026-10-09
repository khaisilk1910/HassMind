# HassMind v1.5.5 — Ngữ cảnh hội thoại liên tiếp (Logic-First)

## Điểm mới

- **Theo ngữ cảnh trong cùng phiên Web/Zalo**: các câu đọc tiếp theo như “còn điện áp?”, “nó đang bật hay tắt?” có thể sử dụng Device được xác định chắc chắn từ câu trước.
- **Không lưu giá trị state**: SQLite chỉ lưu `device_id` được chấp thuận qua Knowledge và thời điểm cập nhật; mỗi lần trả lời lấy Registry/States từ Home Assistant.
- **Không gọi AI khi đã rõ**: Logic-First trả về entity có thuộc tính tương ứng và state mới. Câu hỏi phân tích, so sánh, giải thích vẫn đi qua AI cùng lịch sử chat, và AI được cung cấp Device focus đã xác thực khi thích hợp.
- **An toàn**: không dùng focus để phát lệnh; không kế thừa focus khi đổi chủ đề, nêu tên Device khác, phòng khác, hoặc nhiều thiết bị mơ hồ; tự vô hiệu focus khi Device bị gỡ khỏi Knowledge; không dùng ngữ cảnh Web/Zalo cho Scheduler/Event.
- **Giới hạn**: `CONVERSATION_FOCUS_MINUTES=60` theo mặc định; khi hết thời gian thì không tự suy đoán Device.
- **Tải lại trình duyệt**: khôi phục các tin nhắn trong phiên hiện tại (qua API có xác thực). “Phiên mới” tạo session_id mới và ngữ cảnh độc lập.
- **Xử lý Zalo đồng thời**: các lượt chat trùng session/source được thực hiện tuần tự trong một tiến trình để hạn chế sai thứ tự.

## Tương thích và dữ liệu

- Migration tự động thêm bảng `session_device_focus` trong SQLite hiện có. Không thay đổi lược đồ Knowledge, policy Home Assistant hay danh sách công cụ.
- Giữ nguyên các volume `/data` và `/knowledge` khi nâng cấp; không xóa hoặc dựng lại SQLite để nâng phiên bản.
- Bản nâng cấp này **không** tạo chức năng tự phân tích toàn bộ chủ đề bằng logic khi không có Device: những vấn đề hội thoại chung vẫn dựa vào lịch sử mà AI Agent đã có.

## Kiểm tra thủ công sau khi deploy

1. `xem ổ cắm bơm nước trạng thái ra sao` → báo cáo đầy đủ entity/state.
2. `còn điện áp?` → chỉ trả sensor voltage của Device trước bằng state mới.
3. `nó đang bật hay tắt?` → đọc switch/light/fan thuộc Device (không điều khiển).
4. `tại sao điện áp đó thấp?` → gọi AI phân tích với ngữ cảnh; không được tự phát lệnh.
5. Dùng Phiên mới hỏi `còn điện áp?` → không được tự lấy Device của phiên trước.
6. Tải lại trang và tiếp tục cùng phiên; tin nhắn phải hiển thị lại.
7. Nếu truy vấn riêng `entity_id`, giữ nguyên xử lý entity của v1.5.4.
