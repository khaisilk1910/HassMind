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

## v1.2.5 performance events

For current-state latency diagnostics, look for:

- `ha_state_cache_refreshed`: a complete HA `/api/states` snapshot was loaded.
- `ha_ws_connected`: persistent state event stream is active; current-state reads can be served from RAM.
- `tool_batch_parallel_started` / `tool_batch_parallel_completed`: multiple read-only tools were executed concurrently.
- `llm_request_completed.duration_ms`: model-side latency for each agent round.
- `tool_call_completed.duration_ms`: individual tool latency.
- `chat_completed.duration_ms`: total agent latency.
- `zalo_agent_reply_completed.outbound_chunks`: number of Zalo messages used for a long answer.

If `llm_request_completed.duration_ms` dominates while HA tool calls are already fast, changing HA cache settings will not materially reduce total time; tune the OpenAI-compatible model/provider or shorten conversation/output instead.

## v1.2.8 Zalo rich-text events

- `zalo_rich_text_compiled`: outbound Zalo markup was compiled to clean `msg` + zca-js `styles[]`; inspect `styles_count` to confirm rich formatting was generated.
- `zalo_rich_text_styles_rejected`: the companion server explicitly rejected `styles` with HTTP 400/422, so HassMind retried once with already-clean plain text.

If the Zalo client still shows raw `#` or `**` on v1.2.8, verify the running image version first. A genuine v1.2.8 rich-text send should have `styles_count > 0` for formatted content and the JSON request body should contain `message.styles`.
