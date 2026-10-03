# HassMind v1.2.0 — QA report

Ngày rà soát: 2026-10-03.

## Static/syntax validation

Đã chạy và đạt:

- `python -m compileall -q app`
- `node --check static/app.js`
- `node --check static/login.js`
- `sh -n setup.sh`
- Parse YAML bằng PyYAML cho:
  - `docker-compose.yml`
  - `docker-stack.yml`
  - `portainer-stack.yml`
  - `portainer-stack-opt.yml`
  - `config/mcp_servers.yaml`
- Kiểm tra HTML/JavaScript mapping: không có duplicate DOM id và mọi `getElementById` được dùng trong JS đều có phần tử tương ứng.
- Kiểm tra CSP compatibility: không có inline `<script>` và không dùng inline `onclick=`.
- Mỗi dashboard panel đều có `help-box` mô tả mục đích/cách dùng/ví dụ.
- Không còn browser storage key `hassmind_token`; API token chỉ được quản lý trong Settings.

## FastAPI/authentication smoke test

Đã chạy bằng `FastAPI TestClient` với database/log/runtime-secret tạm và IP client thuộc LAN allowlist:

- `/health` trả đúng `{ "ok": true }`.
- `/` khi chưa đăng nhập trả `303 -> /login`.
- `/login` tải thành công.
- Login sai trả `401`.
- Login đúng tạo admin session + CSRF cookie/token.
- `/` sau login tải dashboard có `Settings` và `Giới thiệu`.
- `/api/auth/me`, `/api/settings/security`, `/api/auth/audit` hoạt động.
- Request thay đổi trạng thái bằng admin session nhưng thiếu CSRF trả `403`.
- Xoay HassMind API token từ Settings hoạt động; token runtime mới thay thế token cũ cho external API authentication.
- Password change hoạt động và giữ phiên hiện tại.
- Recovery Key rotation từ Settings hoạt động; nguồn chuyển sang `runtime_file`, khóa cũ hết hiệu lực ngay và khóa mới dùng được cho reset.
- Forgot-password với Recovery Key sai thất bại; Recovery Key đúng đặt lại password và thu hồi phiên cũ.
- IP ngoài `ADMIN_ALLOWED_NETWORKS` bị chặn `403` trên web-admin surface.
- API/admin response có security headers và `Cache-Control: no-store`.

## Secret redaction / migration hardening

Đã tạo dữ liệu legacy giả lập chứa secret trước startup và xác minh:

- rotating log cũ được scrub khi startup;
- `events.payload` cũ được scrub;
- `tool_audit.arguments/result/error` cũ được scrub;
- API token, admin password, Recovery Key và token mới không xuất hiện dạng plaintext trong log sau test;
- redaction vẫn giữ `[REDACTED]` marker để điều tra log biết đã có dữ liệu bị che.

## File permission test

Trong runtime test:

- SQLite DB: `0600`;
- parent data directory: `0700`;
- log file: `0600`;
- runtime API token: `0600`.

`setup.sh` cũng được chạy trong thư mục tạm và xác minh:

- tạo được cryptographically-random admin/API/recovery secrets;
- secret files có mode `0600`;
- script không in secret value ra stdout.

## Docker/production checks

Đã rà soát cấu hình để giữ:

- non-root `10001:10001`;
- root filesystem `read_only`;
- `cap_drop: ALL`;
- `no-new-privileges:true`;
- `/tmp` tmpfs với `noexec,nosuid,nodev`;
- PID limit;
- Docker log rotation;
- secret mount qua `/run/secrets/*` trong Compose stack ưu tiên.

## Giới hạn của môi trường QA

Môi trường QA không có Home Assistant, Gemini/Zalo/Camera/FaceDetect thật để chạy end-to-end. Home Assistant URL trong smoke test cố ý trỏ tới port không lắng nghe để xác minh app vẫn hoạt động khi HA disconnected. Package MCP/OpenAI được stub tối thiểu trong smoke test để không phát sinh network call; Docker image thực tế cài dependency từ `requirements.txt`.

Không có tool redaction nào có thể chứng minh tuyệt đối rằng mọi chuỗi bí mật tùy ý từng xuất hiện trong log lịch sử đều được nhận diện. Vì vậy `SECURITY.md` vẫn khuyến nghị rotate credential và xóa/archive mã hóa log cũ nếu có nghi ngờ từ phiên bản trước.
