# HassMind 1.3.4 — Configured-timezone consistency

## Mục tiêu

Mọi timestamp do HassMind tạo và hiển thị phải dùng timezone đã cấu hình cho container, thay vì một số thành phần vẫn cố định UTC (`+00:00`). Trường hợp điển hình ở v1.3.3 là Scheduler hiển thị `next=...+00:00` và `last=...+00:00` dù stack đã khai báo `TZ=Asia/Ho_Chi_Minh` / `TIMEZONE=Asia/Ho_Chi_Minh`.

## Thay đổi

- Thêm `app/time_utils.py` làm nguồn thời gian dùng chung cho HassMind.
- `TIMEZONE` là cấu hình ứng dụng hiện tại; nếu không có thì fallback sang `TZ`, sau đó mặc định `Asia/Ho_Chi_Minh`.
- Khi ứng dụng khởi động, HassMind đồng bộ lại cả `TIMEZONE` và `TZ`, gọi `tzset()` trên nền tảng hỗ trợ và fail-fast nếu tên IANA timezone không hợp lệ.
- Docker image cài system `tzdata`; `requirements.txt` cũng có Python `tzdata` để `zoneinfo` hoạt động ổn định trong slim image.
- `Dockerfile`, Compose, Docker Stack và Portainer Stack đều khai báo `TZ`/`TIMEZONE`.
- Tất cả timestamp mới trong SQLite, auth/session, approvals, events, Knowledge, integration config, notification preferences, audit và application logs dùng timezone cấu hình.
- Scheduler tạo `next_run` và `last_run` trong timezone cấu hình. Truy vấn job đến hạn dùng `julianday(...)`, nên vẫn so sánh đúng instant khi dữ liệu cũ còn offset khác hoặc timezone có DST.
- Cooldown Event rule và TTL Approval parse timestamp theo offset và chuyển về timezone cấu hình trước khi tính toán.
- Session cleanup dùng `julianday(...)` thay vì so sánh chuỗi ISO.
- Khi khởi động, timestamp cũ trong các bảng SQLite được chuyển sang offset của timezone cấu hình mà không thay đổi instant. Metadata thời gian trong `knowledge_index_state`, `knowledge_scans` và `knowledge_control.latest_scan` cũng được chuyển đồng bộ để không tạo cảnh báo stale giả.
- Log cũ được normalize timezone trong bước scrub-on-start mặc định.
- UI không còn dùng `new Date(...).toLocaleString()` cho timestamp server. Nó hiển thị trực tiếp wall-clock + offset server, tránh trình duyệt tự đổi sang timezone khác.
- `/health`, `/api/status`, diagnostics và startup log công bố timezone đang dùng.

## Tương thích dữ liệu

Không cần xóa database. Migration timestamp chạy idempotent khi startup. Ví dụ:

`2026-10-04T11:27:57.027022+00:00` → `2026-10-04T18:27:57.027022+07:00`

Hai giá trị trên là cùng một thời điểm tuyệt đối; chỉ khác timezone biểu diễn.
