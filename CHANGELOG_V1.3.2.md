# HassMind 1.3.2 — notification routing, editable automations và Review queue gọn hơn

Bản 1.3.2 mở rộng v1.3.1 theo hướng vận hành thực tế, không thay đổi nguyên tắc an toàn của approval/Knowledge.

## Knowledge Review changes

- Hàng đợi Review changes chỉ hiển thị tối đa 4 proposal có trạng thái `stale`/đã lỗi thời. Các proposal khác vẫn giữ theo giới hạn API hiện tại và toàn bộ lịch sử vẫn có trong Knowledge audit.
- Danh sách Review changes có `max-height` và cuộn nội bộ, nên số proposal lớn không kéo dài cả trang.
- Giữ nguyên chẩn đoán conflict chi tiết và cơ chế Dry-run → Approve/Re-index của v1.3.1.

## Notification routing

- Thêm lớp `app/notifications.py` làm điểm định tuyến thông báo chung.
- Các tính năng có thông báo vận hành gồm Approvals, Scheduler, Event rules và Knowledge monitor đều có lựa chọn `mobile` hoặc `zalo`.
- Khi chọn Zalo, target được resolve theo thứ tự: `thread_id` của tính năng/job/rule → Thread ID thông báo mặc định trong Zalo integration → thread cụ thể đầu tiên trong Allowed thread IDs. Wildcard `*` không bao giờ được dùng làm outbound target.
- Zalo notification sử dụng chính `ZaloClient.send_message`, do đó đi qua cùng `build_zalo_message_content()` như phản hồi chat: `message.msg` sạch + `styles[]` thay vì hiển thị Markdown thô.
- Mobile notification được chuyển sang plain text có emoji/bullet; Markdown/pseudo-markup bị loại bỏ trước khi gọi Home Assistant notify.
- Approvals có preference riêng trong SQLite (`notification_preferences`) và vẫn giữ action buttons khi kênh là Home Assistant mobile. Nếu gửi proposal qua Zalo, nội dung hướng người dùng về Web Admin để Approve/Reject.

## Scheduler và Event rules

- Bổ sung `PUT /api/jobs/{id}` và `PUT /api/event-rules/{id}` để sửa cấu hình hiện có.
- Web Admin có nút **Sửa** cho từng job/rule, nạp lại dữ liệu vào form và lưu thay đổi.
- Khi sửa, trạng thái enabled/disabled hiện tại được giữ nguyên. Scheduler đang enabled sẽ tính lại `next_run` theo lịch mới.
- Thêm `notify_channel` và `zalo_thread_id` vào bảng `jobs`/`event_rules`; migration tự thêm cột với default tương thích dữ liệu cũ.

## Zalo Integration

- Web Admin → Integrations → Zalo có thêm `Thread ID thông báo mặc định` và `Loại thread thông báo (0=user, 1=group)`.
- Có thể cấu hình tương đương qua `ZALO_NOTIFICATION_THREAD_ID` và `ZALO_NOTIFICATION_THREAD_TYPE` nếu triển khai bằng environment.

## Tương thích dữ liệu

- `init_db()` tự migrate database cũ; không cần xóa SQLite.
- Job/rule cũ mặc định dùng `mobile` và `zalo_thread_id=''`.
- Knowledge proposal cũ không bị xóa; chỉ giới hạn số proposal stale được trả về hàng đợi Review.
