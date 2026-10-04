# HassMind v1.2.0 — Security hardening

Tài liệu này mô tả security boundary của Web Admin, secret, log và Docker. Mục tiêu là giảm tối đa khả năng lộ credential và giới hạn blast radius khi dashboard hoặc một integration gặp lỗi.

## 1. Web Admin

Dashboard `/` không chấp nhận HassMind API token làm phiên đăng nhập. Browser phải đăng nhập bằng tài khoản admin tại `/login`.

Cơ chế chính:

- Mật khẩu hash bằng Argon2id; plaintext không lưu trong SQLite.
- Session token tạo bằng CSPRNG; SQLite chỉ lưu SHA-256 của session token.
- CSRF token riêng từng phiên; mọi request thay đổi trạng thái từ browser phải có `X-CSRF-Token` hợp lệ.
- Cookie `SameSite=Strict`; session cookie `HttpOnly`.
- Session có absolute TTL và idle timeout.
- Sai mật khẩu bị account lockout và rate limiting.
- Username không tồn tại vẫn chạy Argon2 verify giả để giảm timing-based username enumeration.
- Password change thu hồi mọi phiên khác; password recovery thu hồi toàn bộ phiên.
- Network allowlist mặc định chỉ cho localhost + RFC1918 trên admin/API surface.
- CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy` và các cross-origin headers được bật.
- Response `/api/*`, `/` và `/login` dùng `Cache-Control: no-store`.
- OpenAPI/Swagger/Redoc bị tắt ở production app.

### HTTP LAN và HTTPS

Với truy cập trực tiếp như `http://192.168.31.100:8090`, phải để:

```dotenv
ADMIN_COOKIE_SECURE=false
```

HTTP không mã hóa traffic trên LAN. Nếu cần mức bảo mật cao hơn, đặt reverse proxy HTTPS/VPN ở trước HassMind và chuyển thành:

```dotenv
ADMIN_COOKIE_SECURE=true
```

Không expose `8090` trực tiếp ra Internet.

### Reverse proxy và IP allowlist

HassMind cố ý dùng IP kết nối TCP thực tế (`request.client`) và **không tin** `X-Forwarded-For` mặc định. Khi reverse proxy chạy cùng host, HassMind sẽ thấy IP của proxy. Do đó network allowlist không thay thế ACL/VPN/firewall ở reverse proxy.

## 2. Quên mật khẩu / Recovery Key

HassMind không phụ thuộc email service để recovery. `admin_recovery_key` là khóa khôi phục offline.

- Giữ `secrets/admin_recovery_key.txt` ngoài Git và backup mã hóa.
- Trong Settings có thể xoay Recovery Key sau khi xác nhận mật khẩu admin. Khóa runtime mới được lưu tại `/data/secrets/admin_recovery_key` mode `0600` và có ưu tiên cao hơn bootstrap secret.
- `secrets/admin_password.txt` là bootstrap-only. Khi đổi/reset mật khẩu, hệ thống chỉ cập nhật Argon2id hash trong SQLite; không ghi plaintext password mới trở lại secret file.
- Sau khi rotate Recovery Key, `secrets/admin_recovery_key.txt`/Docker secret cũ không còn là khóa hiện hành; với bind mount `/opt/hassmind/data:/data`, root trên host có thể đọc khóa runtime ở `/opt/hassmind/data/secrets/admin_recovery_key`.
- Recovery Key mới chỉ trả về một lần cho browser; khi rời Settings giá trị one-time bị xóa khỏi DOM.
- Không gửi Recovery Key vào chat, issue tracker hoặc log.
- Reset thành công sẽ thay password hash và xóa toàn bộ admin sessions.
- Nếu mất cả password và Recovery Key, operator phải thực hiện recovery trực tiếp trên host/SQLite theo quy trình quản trị riêng; web không có bypass.

## 3. HassMind API token

API token dành cho client ngoài dashboard. Nguồn đọc theo thứ tự ưu tiên:

1. `/data/secrets/hassmind_api_token` — token được xoay từ Settings.
2. Docker secret `/run/secrets/hassmind_api_token`.
3. Environment `API_TOKEN` — chỉ nên dùng khi không thể dùng Docker secrets.

Khi xoay token trong Settings, admin phải xác nhận password hiện tại. Token ngẫu nhiên mới chỉ được trả về một lần trong response tạo token.

Browser dashboard không lưu API token trong `localStorage`.

## 4. Redaction log và audit

Redaction được áp dụng trước khi ghi structured log và trước khi ghi `events`/`tool_audit` mới.

Các nhóm được che gồm:

- password/passwd/recovery key/private key;
- token/access token/refresh token;
- API key/client secret/credential;
- Authorization/Bearer;
- cookie;
- JWT;
- OpenAI/GitHub/Telegram token pattern phổ biến;
- Zalo webhook secret trong URL;
- các secret hiện đang cấu hình, bằng exact-value replacement.

Mặc định:

```dotenv
LOG_INCLUDE_CONTENT=false
LOG_SCRUB_EXISTING_ON_START=true
AUDIT_SCRUB_EXISTING_ON_START=true
```

Hai cờ scrub thực hiện best-effort sanitization log rotation và event/tool-audit cũ khi startup. Không có bộ redactor nào chứng minh có thể nhận ra mọi chuỗi secret tùy ý trong lịch sử cũ. Nếu nghi ngờ phiên bản trước từng log credential, hãy xóa/archive mã hóa `data/logs/hassmind.log*` và xoay credential liên quan.

## 5. File permissions

- `/data`, `/data/logs`, `/data/secrets`: mode `0700` khi ứng dụng có thể đặt quyền.
- SQLite và runtime secret: mode `0600`.
- `setup.sh` đặt `umask 077` và `secrets/*.txt` mode `0600`.
- Runtime secret được ghi qua temporary file rồi `os.replace()` để tránh ghi dở dang.
- Logger từ chối ghi qua symbolic link ở đường dẫn log chính.

## 6. Docker hardening

Compose/stack mặc định:

```text
user: 10001:10001
read_only: true
cap_drop: ALL
no-new-privileges:true
tmpfs /tmp: noexec,nosuid,nodev
pids_limit: 256
Docker json-file rotation
```

Container không mount Docker socket, không chạy privileged và không cần Linux capability bổ sung.

`network_mode: host` được giữ để tương thích với Home Assistant và các companion service đang publish trên localhost. Đây là trade-off: host networking giảm network isolation so với bridge. Bù lại, hãy giữ `ADMIN_ALLOWED_NETWORKS`, firewall host, và không expose 8090 ra WAN.

## 7. Docker secrets so với environment variables

Ưu tiên `docker-compose.yml`/`docker-stack.yml` vì credential được mount qua `/run/secrets/*`.

`portainer-stack.yml` hỗ trợ environment variables để deploy thuận tiện. Người có quyền inspect container/Portainer có thể đọc environment; vì vậy cách này yếu hơn Docker secrets về secret-at-rest.

## 8. Checklist production

- Chạy `sudo ./setup.sh` và kiểm tra `secrets/*.txt` là `0600`.
- Đổi admin password ngay sau lần login đầu.
- Cất Recovery Key offline/backup mã hóa.
- Giữ `LOG_INCLUDE_CONTENT=false` trừ khi debug ngắn hạn.
- Chỉ bật side-effect integration cần thiết.
- Không commit `.env`, `secrets/`, `data/`.
- Không expose port 8090 ra Internet; dùng VPN/HTTPS reverse proxy nếu truy cập từ xa.
- Khi dùng HTTPS, bật `ADMIN_COOKIE_SECURE=true`.
- Xoay HA token/LLM key/API token nếu nghi ngờ từng bị ghi vào log cũ.
