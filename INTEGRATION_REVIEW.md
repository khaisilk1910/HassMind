# HassMind v1.1.0 - Source review & integration map

Phạm vi rà soát: 9 project companion/custom-component do người dùng cung cấp + HassMind v1 gốc.

## Kiến trúc được chọn

- HassMind vẫn là stack độc lập, `network_mode: host`.
- Companion service có HTTP/TCP API: adapter trực tiếp có schema (`camera-tts-ezviz`, `facedetect`, `zalo-bot-server`, Wyoming health).
- Home Assistant custom component: truy cập qua HA REST/WebSocket (`EVN-CSKH-Monitor`, `am-lich-viet-nam`, `shopping_history`, `yt_dlp_hass`).
- Gemini FastAPI: dùng trực tiếp làm OpenAI-compatible model backend; không bọc thêm proxy.
- Không gom database/volume của các container khác vào HassMind.
- Không cấp cho model generic raw-HTTP tool để tránh biến adapter thành SSRF/unrestricted service tunnel.

## Những interface đã đối chiếu từ source

### gemini-fastapi-multi-account
- `GET /v1/models`
- `POST /v1/chat/completions`
- request model có `tools` + `tool_choice`
- stack có `CONFIG_SERVER__API_KEY`

### camera-tts-ezviz
- `/health` public; action API kiểm tra `X-API-Key` hoặc Bearer.
- `/cameras`, `/say/<camera_id>`, `/media/<camera_id>`, `/ptz/<camera_id>`, `/stop/<camera_id>`, `/jobs/<job_id>`.
- PTZ directions được whitelist đúng source.
- Default host-network API port 8124, intercom 8125.

### facedetect / IRIS
- `/api/health`, `/api/summary`, `/api/events`, `/api/people`, `/api/cameras`.
- Event filters: `page`, `limit`, `event_type`, `camera_id`, `person_id`.
- Stack chuẩn publish 8080:80; Intel stack publish 8181:80.
- Source đã có MQTT + Home Assistant webhook, nên HassMind không tạo event bus thứ ba.

### zalo-bot-server
- Session auth: `POST /api/login`, `GET /api/check-auth`.
- `GET /api/accounts` trả `ownId`, `phoneNumber`, `isOnline`.
- `POST /api/sendMessageByAccount`; `threadId` được ép String ở server.
- Webhook v2 CRUD ở `/api/webhook-accounts/*`.
- Event message bổ sung `threadId` string, `_threadRef`, `_threadType`, `_accountId`; self-message bị filter.
- Webhook delivery timeout mặc định 10 giây.
- HassMind auto-registration chỉ thêm destination riêng, không xóa/sửa destination khác.

### EVN-CSKH-Monitor
- HA HTTP prefix `/api/evncskh`.
- `/ping`, `/options`, `/summary/{account}`, `/daily/{account}`, `/monthly/{account}`.

### am-lich-viet-nam
- service `am_lich_viet_nam.convert_date`.
- `SupportsResponse.ONLY` -> HassMind gọi REST với `return_response`.

### shopping_history
- WebSocket command `shopping_history/get_data` với `entry_id`, optional `year`.
- Services `add_order`, `edit_order`, `delete_order`.
- Sensor attributes có `shopping_history`, `config_entry_id`, `nam` để discovery profile/year.

### yt_dlp_hass
- `search` và `get_job`: `SupportsResponse.ONLY`.
- `download` và `play`: `SupportsResponse.OPTIONAL`.
- HassMind gọi `return_response` để nhận kết quả có cấu trúc.

### wyoming-vietnamese-prosody
- Wyoming STT+TTS endpoint port 10300.
- HassMind không duplicate Wyoming wire protocol; Home Assistant là boundary cho `tts.speak`.

## Policy mặc định

- Camera TTS actions: on khi adapter được enable, có thể tắt riêng.
- Zalo outbound: off.
- Zalo agent auto-reply: off.
- Shopping add/edit: off.
- Shopping delete: off và yêu cầu cả mutation + delete.
- yt-dlp playback: on.
- yt-dlp downloads: off.
- Wyoming TTS: on khi adapter được enable.

## File HassMind chính đã thay đổi/thêm

- `app/settings.py`
- `app/ha.py`
- `app/ha_integrations.py` (new)
- `app/integrations/*` (new)
- `app/tools.py`
- `app/main.py`
- `.env.example`
- `docker-compose.yml`, `docker-stack.yml`, `portainer-stack.yml`
- `setup.sh`
- `static/index.html`
- `config/system_prompt.txt`
- `config/skills/integration-orchestration.md` (new)
- `secrets/README.txt` (new)
- `README_VI.md`
- `VERSION` -> 1.1.0

## Validation thực hiện trên gói v1.1.0

- `python -m compileall -q app`: PASS.
- Parse AST toàn bộ `app/**/*.py`: PASS.
- Parse YAML cho `docker-compose.yml`, `docker-stack.yml`, `portainer-stack.yml`, `config/mcp_servers.yaml`: PASS.
- `sh -n setup.sh`: PASS.
- Adapter smoke test bằng fake HA/client: PASS cho Shopping profile discovery, service `return_response`, yt-dlp search, auto-select Wyoming TTS entity, Zalo webhook-preservation và Camera TTS job lookup.
- Docker daemon không có trong môi trường build hiện tại, nên chưa chạy `docker compose config/build/up` hoặc live end-to-end tới các container thật.
- Python host dùng để review không cài đầy đủ runtime dependency `mcp`/`openai`; Dockerfile vẫn cài chúng từ `requirements.txt` khi build image.
