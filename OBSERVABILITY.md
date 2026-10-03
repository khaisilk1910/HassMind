# HassMind v1.2.0 - Observability / Debugging

Bản này thêm structured logging và giao diện chẩn đoán để truy vết lỗi theo `request_id`, `session_id`, component và thời gian xử lý.

## Log destinations

- stdout/stderr của container: dùng `docker logs hassmind`.
- rotating file: `/data/logs/hassmind.log`.
- in-memory ring buffer: hiển thị trong tab **Logs** và API `GET /api/logs`.
- tool audit vẫn lưu riêng trong SQLite và hiển thị ở tab **Tool audit**.

## Các trường log chính

- `ts`: UTC timestamp tới milliseconds.
- `level`: DEBUG/INFO/WARNING/ERROR/CRITICAL.
- `component`: api, agent, home_assistant, integration_http, scheduler, telegram, mcp...
- `event`: mã sự kiện ổn định để tìm kiếm.
- `request_id`: liên kết một HTTP request từ browser tới backend.
- `session_id`: liên kết toàn bộ một phiên chat/job/event/Zalo.
- `duration_ms`: latency của HTTP/LLM/tool/integration.
- `exception.type`, `exception.message`, `exception.traceback`: traceback đầy đủ khi có exception.

## Bảo vệ secret

Logger tự động che các key chứa token, password, secret, API key, Authorization, cookie và access token. Zalo webhook secret trong URL cũng bị che.

`LOG_INCLUDE_CONTENT=false` là mặc định. Khi cần debug sâu, tạm bật:

```dotenv
LOG_LEVEL=DEBUG
LOG_INCLUDE_CONTENT=true
```

Sau khi sửa lỗi nên đưa `LOG_INCLUDE_CONTENT=false` trở lại vì prompt/result có thể chứa dữ liệu nhà riêng.

## API chẩn đoán

- `GET /health`: health không cần token.
- `GET /api/status`: trạng thái ngắn.
- `GET /api/diagnostics`: runtime/database/log configuration an toàn.
- `GET /api/logs?limit=250&level=ERROR&component=agent&q=request-id`: lọc log.
- `GET /api/logs/export`: tải NDJSON.
- `GET /api/audit`: tool audit SQLite.
- `POST /api/client-log`: frontend tự gửi JavaScript exception/unhandled rejection về backend log.

Tất cả endpoint `/api/*` ở trên yêu cầu `X-HassMind-Token` như các API hiện có.

## Debug theo Request ID

Khi giao diện báo lỗi API, UI hiển thị `Request ID`. Mở tab **Logs**, dán Request ID vào ô tìm kiếm. Bạn sẽ thấy lần lượt request, agent, LLM, tool và integration có cùng correlation context.
