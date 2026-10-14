# HassMind v1.5.9 — Security hardening

Đầu vào: `HassMind-v1.5.8-modern-admin-ui.zip`. Không thay đổi giao diện Aurora, nhật ký phân trang, hạn lưu chat theo ngày hoặc luồng thực thi HA thông thường.

## Phát hiện và vá

| Mức ưu tiên | Vấn đề | Khắc phục |
| --- | --- | --- |
| **Nghiêm trọng** | Telegram đã cấu hình token nhưng `Allowed Chat IDs` trống đồng nghĩa bot nhận chat bất kỳ, từ đó có thể gửi lệnh tới agent Home Assistant. | Đổi sang **deny-by-default**; kiểm tra Chat ID, sender ID và loại chat. Group chỉ cho user ID trong `TELEGRAM_ALLOWED_USER_IDS`. Chặn sender_chat/bot, reject tin nhắn không có timestamp hoặc quá hạn mặc định 300 giây. |
| Cao | API admin kiểm tra IP kết nối nhưng chưa kiểm tra Host header hoặc Origin, tạo khoảng hở nếu trình duyệt/proxy có cấu hình không an toàn. | Whitelist Host LAN và các host được khai báo; chặn cross-origin write. Với tên miền HTTPS cần `ADMIN_ALLOWED_HOSTS`. |
| Cao | `uvicorn` có thể tin IP trong forwarded headers theo mặc định khi reverse proxy ở localhost, dẫn đến sai lệch IP khi ACL. | Chạy với `proxy_headers=False`, không lấy IP từ X-Forwarded-For. |
| Trung bình–cao | Argon2 trong async handler chạy đồng bộ; nhiều lần đăng nhập đồng thời có thể gây nghẽn event loop/CPU; bộ đếm failure theo username có thể tăng số key theo thời gian. | Chuyển sang background threads, semaphore toàn cục/từng IP, cap + purge rate key. |
| Trung bình | Webhook nhận payload không được kiểm tra giới hạn số byte thật, dễ bị replay/flood. | Request size guard (stream/Content-Length), limit 120 request/phút/IP + 16 Zalo agent replies đồng thời. |
| Trung bình | Ghi runtime secret sử dụng đường dẫn `.tmp` cố định, có rủi ro ghi qua symlink hoặc đè chéo khi thay đổi đồng thời. | Tạm ngẫu nhiên 0600, fsync và os.replace, kiểm tra tên secret an toàn. |

## Cấu hình mới cần lưu ý

- `TELEGRAM_ALLOWED_CHAT_IDS` — bắt buộc nếu muốn tương tác Telegram; rỗng nghĩa là từ chối.
- `TELEGRAM_ALLOWED_USER_IDS` — bắt buộc thêm nếu dùng group/supergroup; private chat vẫn dùng Chat ID whitelist và xác thực người gửi.
- `TELEGRAM_MAX_MESSAGE_AGE_SECONDS=300` — từ chối lệnh cũ sau khởi động lại.
- `ADMIN_ALLOWED_HOSTS=` — khai báo thêm exact FQDN nếu không truy cập qua IP nội bộ/`.local`/`.home.arpa`.
- `MAX_REQUEST_BODY_BYTES=2097152` — giới hạn API thường, riêng Knowledge proposal tối đa 12 MiB.

## Giới hạn

Chưa kiểm thử penetration test trên dịch vụ thật, chưa scan CVE toàn bộ cây dependency/container image bằng công cụ ngoài, chưa kiểm thử end-to-end với Home Assistant/Telegram/Zalo thật. Các bất thường hạ tầng (TLS, firewall, quyền truy cập Docker, reverse proxy, quyền nguồn bí mật) cần kiểm tra khi triển khai.
