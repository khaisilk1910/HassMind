# HassMind v1.2.2 — QA report

Ngày rà soát: 2026-10-03.

## Phạm vi sửa lần này

- Clipboard Recovery Key/API token khi dashboard chạy HTTP trong LAN.
- Vòng đời admin password / Recovery Key và thông tin hiển thị trong Settings/Login/README.
- Render `**...**` trong câu trả lời Chat thành phần nhấn mạnh có màu, không hiện dấu `**`.
- Đồng bộ version/cache-busting lên 1.2.2.

## Static / syntax validation

Đã chạy và đạt:

- `python3 -m compileall -q app`
- `node --check static/app.js`
- `node --check static/login.js`
- `sh -n setup.sh`
- Parse YAML bằng PyYAML cho `docker-compose.yml`, `docker-stack.yml`, `portainer-stack.yml`, `portainer-stack-opt.yml`, `config/mcp_servers.yaml`.
- Kiểm tra duplicate DOM id và mapping toàn bộ `$('<id>')` trong `static/app.js`: không có id thiếu.
- Kiểm tra version đồng bộ: backend, package, dashboard và login đều là `1.2.2`.

## Clipboard test

Đã kiểm tra bằng Node mock DOM:

- Khi `isSecureContext=false`, code **không gọi** Clipboard API hiện đại.
- Fallback tạo textarea tạm, select nội dung và gọi `document.execCommand('copy')` ngay trong click flow.
- Fallback trả trạng thái thành công và xóa textarea tạm.
- Nếu fallback cũng bị browser chặn, code select input gốc để người dùng chỉ cần nhấn Ctrl/Cmd+C.

Cùng helper được dùng cho cả Recovery Key và HassMind API token.

## Chat emphasis test

Đã kiểm tra parser với câu:

`Hôm nay là **Thứ Bảy**, ngày **03 tháng 10 năm 2026**.`

Kết quả token hóa giữ nguyên nội dung nhưng loại marker `**`; hai đoạn `Thứ Bảy` và `03 tháng 10 năm 2026` được đánh dấu strong. Marker không đóng cặp được giữ nguyên thay vì làm mất dữ liệu.

Renderer không dùng `innerHTML` cho nội dung chat; nó tạo `TextNode` và phần tử `strong`, vì vậy nội dung LLM không được diễn giải thành HTML tùy ý.

## Admin password / Recovery Key API smoke test

Đã chạy FastAPI `TestClient` với SQLite/runtime-secret tạm và IP `127.0.0.1`:

- Bootstrap admin bằng password ban đầu thành công.
- Login password ban đầu thành công.
- `/api/settings/security` báo `password_storage=argon2id_hash_only` và `bootstrap_password_is_initial_only=true`.
- Đổi password thành công.
- Password bootstrap ban đầu vẫn giữ nguyên ở nguồn bootstrap, nhưng **không còn đăng nhập được**.
- Password mới đăng nhập được.
- Rotate Recovery Key thành công.
- Recovery Key mới được ghi vào runtime file và `admin_recovery_key_source()` chuyển thành `runtime_file`.
- Recovery Key bootstrap cũ bị từ chối sau rotate.
- Recovery Key runtime mới reset password thành công.
- Password trước reset không còn đăng nhập được; password sau reset đăng nhập được.
- `admin_users.password_hash` là Argon2 hash và không chứa plaintext password mới.

## Kết luận về hai file `/opt/hassmind/secrets/*`

`admin_password.txt` và `admin_recovery_key.txt` là nguồn bootstrap. Chúng không phải cơ chế đồng bộ credential hiện hành sau khi đổi từ UI.

- Password hiện hành: chỉ lưu Argon2id hash trong SQLite, không có plaintext để `cat` xem lại.
- Recovery Key sau rotate: lưu runtime tại `/data/secrets/admin_recovery_key` mode `0600` và được ưu tiên hơn bootstrap key.
- Nếu stack mount `/opt/hassmind/data:/data`, host path tương ứng là `/opt/hassmind/data/secrets/admin_recovery_key`.

Thiết kế này được giữ nguyên để tránh ghi password hiện hành dạng plaintext xuống disk chỉ nhằm mục đích xem lại.

## Giới hạn QA

Môi trường QA không cài package `openai` và `mcp`; smoke test API đã dùng import stub tối thiểu cho hai dependency này và không gọi network/LLM/MCP. Các dependency thực tế vẫn được cài từ `requirements.txt` trong Docker image.
