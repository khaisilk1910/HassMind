# HassMind v1.3.5

## Scheduler: thông báo có điều kiện

- Thêm `jobs.notify_mode` với hai giá trị `always` và `actionable`; migration tự thêm cột với mặc định `always`.
- Web Admin Scheduler thêm **Khi nào gửi → Chỉ gửi khi có nội dung cần báo**.
- Với `actionable`, Scheduler bổ sung protocol nội bộ vào prompt. Khi agent xác định prompt yêu cầu im lặng và không có kết quả đủ điều kiện, agent trả đúng `__HASSMIND_NO_NOTIFY__`.
- `run_prompt` nhận biết sentinel chính xác và không gọi `send_notification`, do đó không có notification Điện thoại hoặc Zalo.
- Web Admin vẫn lưu `🔕 Không có nội dung cần thông báo.` vào `last_result` để người quản trị biết job đã chạy thành công.
- So khớp sentinel là exact-match để tránh vô tình chặn các phản hồi tự nhiên.
- API tạo/sửa job và tool `schedule_propose` đã hỗ trợ `notify_mode`.

## Tương thích

- Job cũ giữ nguyên hành vi vì mặc định là `always`.
- Không thay đổi schema Event rules.
- Không thay đổi cấu hình kênh Điện thoại/Zalo hiện có.
