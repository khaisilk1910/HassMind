# HassMind 1.3.3 — Scheduler reliability hotfix

Date: 2026-10-04

## Root cause từ log thực tế

Log 1.3.2 cho thấy Scheduler không hỏng ở bước chạy agent. Job `#3` đã hoàn tất `agent.chat`, sau đó mới lỗi khi gửi kết quả qua Zalo:

- payload thành công trước đó: khoảng 855–925 ký tự visible, 40–44 style spans;
- payload lỗi: 1.791 ký tự / 91 styles và 2.025 ký tự / 114 styles;
- Zalo companion trả `HTTP 500 /api/sendMessageByAccount`;
- exception bị đẩy ngược lên `run_prompt()`, khiến Scheduler ghi `job_run_failed` và thay `last_result` bằng lỗi transport dù tác vụ đã hoàn thành.

Ngoài ra, cùng log cho thấy:

- job interval được tạo với `schedule_value=30` nhưng backend âm thầm dùng tối thiểu 60 giây;
- `ha_search_states` đôi khi nhận `limit=""` từ OpenAI-compatible backend và ném `ValueError`.

## Sửa lỗi

### 1. Zalo rich-text chunking trước transport

`split_zalo_message()` giờ kiểm soát đồng thời kích thước chuỗi và số style spans. Mặc định mỗi chunk tối đa 900 ký tự markup và 40 styles — ngưỡng bảo thủ nằm dưới payload đã được quan sát gửi thành công.

Việc chia diễn ra trước request đầu tiên. HassMind vẫn **không retry HTTP 5xx**, tránh nguy cơ gửi trùng khi trạng thái gửi của companion không chắc chắn.

### 2. Notification failure không làm hỏng kết quả Scheduler/Event rule

`run_prompt()` tách lỗi transport khỏi lỗi thực thi agent:

- kết quả agent vẫn được trả về và lưu vào `jobs.last_result`;
- log ghi riêng `system_notification_failed` với traceback;
- tạo event `notification_error` khi có thể;
- cuối `last_result` có cảnh báo ngắn rằng gửi thông báo thất bại và cần xem Logs.

Nhờ đó UI không còn báo cả job thất bại chỉ vì kênh thông báo tạm thời lỗi.

### 3. Interval 30 giây chạy đúng

Scheduler hỗ trợ interval tối thiểu 30 giây. Không còn silent clamp 30 → 60.

- `30` chạy theo 30 giây;
- `<30` trả lỗi rõ ràng;
- daily sai định dạng cũng trả thông báo `HH:MM` rõ ràng;
- create/toggle API chuyển lỗi lịch thành HTTP 400 thay vì lỗi server 500.

UI tự đổi placeholder giữa daily và interval để tránh nhập nhầm.

### 4. Chịu lỗi numeric argument từ model

Các tham số số tùy chọn của tool được parse bảo thủ. Blank/invalid optional values trở về default và vẫn bị giới hạn min/max, thay vì làm hỏng cả tool call.

Điểm này xử lý trực tiếp lỗi log `invalid literal for int() with base 10: ''` ở `ha_search_states` và áp dụng cùng nguyên tắc cho các limit/cooldown/speed/duration tương tự.

## Tương thích

- Không migration database.
- Không thay secrets.
- Không thay schema notification/Scheduler đã có ở 1.3.2.
- Giữ nguyên cơ chế Zalo rich-text `message: {msg, styles}` và fallback plain-text cho 400/422.
