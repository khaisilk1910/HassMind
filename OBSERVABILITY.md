# HassMind v1.2.0 — Observability / Debugging

HassMind dùng structured logging để truy vết lỗi theo `request_id`, `session_id`, component và latency mà không cần đưa secret vào log.

## Log destinations

- stdout/stderr của container: `docker logs hassmind-v1`.
- rotating file: `/data/logs/hassmind.log`.
- in-memory ring buffer: tab **Logs** và `GET /api/logs`.
- tool audit: SQLite + tab **Tool audit**.
- event buffer: SQLite + tab **HA events**.

## Trường log chính

- `ts`: UTC timestamp tới milliseconds.
- `level`: DEBUG/INFO/WARNING/ERROR/CRITICAL.
- `component`: api, agent, home_assistant, integration_http, scheduler, telegram, mcp...
- `event`: mã sự kiện ổn định.
- `request_id`: correlation ID của HTTP request.
- `session_id`: correlation ID của chat/job/event/Zalo.
- `duration_ms`: latency.
- `exception.type`, `exception.message`, `exception.traceback`: exception đã qua redaction.

## Bảo vệ secret

Logger redacts cả theo tên field, pattern trong free-form text và exact value của secret đang cấu hình. Các nhóm chính: password, recovery key, API key, token, Bearer/Authorization, cookie, JWT, webhook secret và credential của integration.

Mặc định:

```dotenv
LOG_LEVEL=INFO
LOG_INCLUDE_CONTENT=false
LOG_SCRUB_EXISTING_ON_START=true
AUDIT_SCRUB_EXISTING_ON_START=true
```

`LOG_INCLUDE_CONTENT=true` chỉ nên bật tạm thời vì prompt/result dù đã redact secret vẫn có thể chứa dữ liệu riêng tư của ngôi nhà.

Khi startup, HassMind best-effort sanitize các file log rotation cũ và event/tool-audit cũ. Với dữ liệu lịch sử từ phiên bản trước, nếu từng có khả năng ghi credential thô thì cách an toàn nhất vẫn là rotate credential và xóa/archive mã hóa log cũ sau khi điều tra.

## API chẩn đoán và authentication

- `GET /health`: public, chỉ trả `{ok:true}` để Docker healthcheck hoạt động mà không lộ cấu hình.
- `GET /api/status`
- `GET /api/diagnostics`
- `GET /api/logs?limit=250&level=ERROR&component=agent&q=request-id`
- `GET /api/logs/export`
- `GET /api/audit`
- `POST /api/client-log`

Dashboard gọi `/api/*` bằng admin session + CSRF. Client ngoài có thể dùng:

```text
X-HassMind-Token: <api-token>
```

API token không còn được nhập ở top bar và không được browser lưu làm thông tin đăng nhập.

## Debug theo Request ID

Khi UI báo lỗi API, lấy `Request ID`, mở tab **Logs** và tìm đúng ID đó. Các log request/backend/tool/integration có cùng correlation context sẽ giúp xác định điểm lỗi.

Ví dụ:

```text
Request ID: a9f0...
```

Tại tab Logs, nhập `a9f0...` vào ô tìm kiếm và lọc `ERROR` nếu cần.
