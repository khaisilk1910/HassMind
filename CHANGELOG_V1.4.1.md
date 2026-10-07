# HassMind v1.4.1 — Advanced Scheduler

## Added
- Scheduler hỗ trợ 5 kiểu lịch: `daily`, `weekly`, `window`, `interval`, `once`.
- `weekly` cho phép chọn tự do T2–CN và chạy tại một giờ cố định.
- `window` cho phép chọn ngày bắt đầu, giờ bắt đầu, giờ dừng và chu kỳ X phút; hỗ trợ khung qua đêm như `23:00 -> 06:00`.
- UI có weekday picker, preset Mỗi ngày / T2–T6 / T7–CN và editor riêng cho từng kiểu lịch.
- `once` chạy một lần và tự disable trước khi gọi agent để giảm nguy cơ chạy lặp.
- Danh sách Scheduler hiển thị lịch theo dạng dễ đọc thay vì JSON thô.

## Changed
- `schedule_propose` của Agent hỗ trợ toàn bộ 5 kiểu lịch mới và mô tả rõ format `schedule_value`.
- `bedroom-climate-comfort` ưu tiên một `window` job cho nhu cầu chạy theo khung giờ, thay vì đề xuất nhiều job hoặc interval 24/7.
- API `JobIn.schedule_value` tăng giới hạn lên 512 ký tự và giới hạn `schedule_type` về các kiểu được hỗ trợ.
- Scheduler runtime tách bước advance lịch; job có cấu hình lịch hỏng sẽ bị disable thay vì lặp lỗi vô hạn.

## Compatibility
- Job `daily` và `interval` cũ giữ nguyên format và tiếp tục hoạt động.
- Không cần migration database mới; các kiểu lịch mới dùng `schedule_value` dạng JSON trong cột TEXT hiện có.
- Notification channel, notify mode, sửa/bật/tắt/xóa job và phân trang 20 job/trang giữ nguyên.

## Window semantics
- `weekdays` dùng `0=T2 ... 6=CN`.
- Với khung qua đêm, weekday là ngày **bắt đầu** khung. Ví dụ chọn T2 với `23:00 -> 06:00` nghĩa là từ 23:00 T2 đến trước 06:00 T3.
- `end` là mốc dừng, không phải một lần chạy bổ sung. `23:00 -> 06:00`, mỗi 60 phút sẽ chạy 23:00, 00:00, 01:00, 02:00, 03:00, 04:00, 05:00 rồi dừng.
