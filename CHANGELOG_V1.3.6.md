# HassMind v1.3.6

## Notification output

- Bổ sung output protocol cho cả `always` và `actionable` để agent trả kết quả notification ngắn gọn, trực tiếp, không lặp câu meta như “Theo đúng yêu cầu”.
- Thêm `clean_notification_result()` trước transport và trước khi lưu kết quả Scheduler/Event rule, sửa các wrapper Markdown hỏng kiểu `*(Theo đúng yêu*(...)\*` mà không thay đổi nội dung thực tế.
- Điện thoại tiếp tục đi qua `format_mobile_notification`: plain text, bỏ Markdown/pseudo-tag, giữ cấu trúc bằng emoji và bullet.
- Zalo tiếp tục dùng rich-text compiler của luồng chat, có chunking transport-safe và fallback `thread_id` theo cấu hình hiện có.

## Tool audit / giao diện

- Tool audit có lựa chọn 20, 50, 100, 200 hoặc 500 bản ghi và vùng cuộn có giới hạn chiều cao.
- Chuyển nhóm menu **Chẩn đoán** xuống sau **Tự động hóa**.

## Scheduler / Event rules

- Scheduler và Event rules hiển thị dạng thu gọn: mặc định chỉ thấy tiêu đề/trạng thái; mở từng mục mới thấy prompt, lịch/cooldown, notification route và nút thao tác.
- Thêm phân trang backend + frontend, cố định 20 mục/trang; endpoint cũ không truyền `page` vẫn trả list để giữ tương thích.
- Event rules thêm `notify_mode=always|actionable`, migration SQLite tự thêm cột `notify_mode TEXT NOT NULL DEFAULT 'always'`.
- Web Admin Event rules thêm trường **Khi nào gửi** giống Scheduler và giữ giá trị khi sửa.

## Tương thích

- Job/rule cũ mặc định `always`, không thay đổi hành vi sau migration.
- API list cũ vẫn tương thích nếu client không dùng tham số phân trang.
- Không thay đổi cấu hình kênh Điện thoại/Zalo hiện có.
