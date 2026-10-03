# HassMind v1.2.0 QA report

## Đã kiểm tra

- `python -m compileall` cho toàn bộ `app/`.
- `node --check` cho JavaScript nhúng trong `static/index.html`.
- Parse YAML cho `docker-compose.yml`, `docker-stack.yml`, `portainer-stack.yml`, `portainer-stack-opt.yml`, `config/mcp_servers.yaml`.
- `sh -n setup.sh`.
- Smoke test FastAPI bằng `TestClient`: startup/shutdown, `/health`, `/api/status`, `/api/diagnostics`, `/api/logs`, `/api/logs/export`, `/api/client-log`, authentication 401.
- Smoke test correlation: log Home Assistant giữ đúng component `home_assistant`, HTTP request dùng component `api` và cùng `request_id`.
- Smoke test redaction: token/password/Authorization/API key/query secret/Zalo webhook secret không xuất hiện ở log.
- SQLite init và rotating log file chạy trong thư mục test writable.

## Giới hạn môi trường QA

Môi trường build này không có Home Assistant/Gemini/Zalo/Camera/FaceDetect thật để chạy end-to-end. Hai dependency `openai` và `mcp` cũng không có sẵn và internet bị chặn, nên smoke test FastAPI dùng stub import tối thiểu cho hai package này. Docker image thực tế sẽ cài dependency từ `requirements.txt` trong lúc GitHub Actions build.
