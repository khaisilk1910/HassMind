# HassMind v1 — AI Agent riêng cho Home Assistant

HassMind v1 chạy **độc lập** với stack Home Assistant hiện có. Container HassMind chỉ kết nối tới HA qua REST/WebSocket và không yêu cầu ghép/chỉnh stack Home Assistant.

## Chức năng v1

- Agent loop + OpenAI-compatible tool calling.
- Home Assistant REST + WebSocket realtime gateway.
- Đọc state, history, entity registry và event gần đây.
- Direct-action allowlist cho các domain ít nhạy cảm.
- Sửa automation/script bằng proposal -> mobile/web approval -> apply -> verify -> audit.
- Optimistic locking: từ chối apply nếu config đã đổi từ lúc proposal.
- Auto rollback nếu apply xong nhưng verify không khớp.
- Rollback proposal có approval riêng.
- SQLite chat memory, audit, events, jobs, event rules.
- Local RAG bằng SQLite FTS từ thư mục `knowledge/`.
- Skill registry từ `config/skills/*.md`.
- Scheduler: job do AI/người dùng tạo luôn ở trạng thái disabled; người dùng bật trên dashboard.
- Event-triggered agent: rule do AI/người dùng tạo luôn disabled; người dùng bật trên dashboard.
- External MCP client.
- Optional SearXNG web search.
- Optional Telegram gateway với allowlist chat ID.
- Web dashboard/chat tại port 8090, bảo vệ bằng `X-HassMind-Token`.

## 1. Điều kiện

- Home Assistant đã chạy trên cùng Linux server và truy cập được từ host tại `http://127.0.0.1:8123`.
- Docker + Docker Compose/Portainer.
- Home Assistant Long-Lived Access Token. Để dùng Config API cho automation/script, tài khoản tạo token phải có quyền admin.
- API key của LLM OpenAI-compatible.

Nếu HA không listen trên host port 8123, đổi `HA_URL` trong `.env` thành địa chỉ HA mà container HassMind có thể truy cập.

## 2. Chuẩn bị

```bash
cp .env.example .env
mkdir -p data knowledge secrets
```

Tạo secret:

```bash
printf '%s' 'HOME_ASSISTANT_LONG_LIVED_TOKEN' > secrets/ha_token.txt
printf '%s' 'YOUR_LLM_API_KEY' > secrets/openai_api_key.txt
openssl rand -hex 32 > secrets/hassmind_api_token.txt
# Telegram không dùng thì vẫn tạo file rỗng:
: > secrets/telegram_bot_token.txt
chmod 600 secrets/*.txt
```

Sửa `.env` tối thiểu:

```dotenv
HA_URL=http://127.0.0.1:8123
HA_NOTIFY_SERVICE=notify.mobile_app_your_phone
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=your_model
```

`OPENAI_MODEL` cần là model mà provider của bạn thực sự hỗ trợ tool/function calling.

## 3. Deploy stack riêng

### Docker Compose

```bash
docker compose -f docker-stack.yml up -d --build
```

### Portainer

Cách thuận tiện nhất là đặt project vào Git repository rồi trong Portainer chọn **Stacks -> Add stack -> Repository**, trỏ tới `docker-stack.yml`. Stack có `build: .`, nên Portainer cần lấy được toàn bộ repository chứ không chỉ mỗi YAML.

Nếu dùng Web editor của Portainer mà không có source build context, hãy build image trước trên server:

```bash
docker build -t hassmind-v1:latest .
```

sau đó bỏ block `build:` khỏi stack và giữ:

```yaml
image: hassmind-v1:latest
```

## 4. Truy cập

```text
http://IP_SERVER:8090
```

Lấy token đăng nhập dashboard:

```bash
cat secrets/hassmind_api_token.txt
```

Paste token vào ô góc phải và bấm **Lưu token**.

Health endpoint không cần token:

```text
http://IP_SERVER:8090/health
```

Không forward port 8090 trực tiếp ra Internet. Nếu cần truy cập ngoài LAN, đặt reverse proxy + TLS + authentication/VPN ở phía trước.

## 5. Approval automation/script

Agent có thể đọc config và tạo proposal nhưng không tự bypass approval.

Luồng:

```text
AI -> ha_get_config
   -> ha_propose_config_change
   -> SQLite snapshot + diff + old hash
   -> HA actionable notification
   -> Duyệt/Từ chối
   -> nếu Duyệt và AUTO_APPLY_AFTER_APPROVAL=true
      -> kiểm tra config hash hiện tại
      -> POST config API
      -> GET verify
      -> applied hoặc auto rollback
```

Bạn cũng có thể duyệt từ tab **Approvals** của dashboard. API web được bảo vệ bằng HassMind API token.

## 6. Direct service policy

Mặc định chỉ cho agent gọi trực tiếp các domain:

```text
light,switch,fan,climate,media_player,scene,input_boolean,input_number,input_select,number,select
```

Các domain sau bị block trực tiếp:

```text
shell_command,hassio,homeassistant,lock,alarm_control_panel,cover,update,button
```

Bạn có thể thay đổi qua `.env`, nhưng nên mở từng domain sau khi đã kiểm tra tool behavior. `script` không nằm trong allowlist mặc định vì script có thể chứa hành động đặc quyền.

## 7. Scheduler

AI có tool `schedule_propose`; dashboard/API cũng có thể tạo job. Mọi job mới đều `disabled`.

Ví dụ daily report:

```text
name: Daily Home Report
schedule_type: daily
schedule_value: 21:00
prompt: Dùng skill daily-home-report để tạo báo cáo nhà hôm nay.
```

Sau khi kiểm tra prompt, bật job trong dashboard.

`interval` có giá trị là số giây và tối thiểu 60 giây.

## 8. Event-triggered agent

Rule mới cũng mặc định disabled.

Ví dụ:

```text
entity_id: binary_sensor.front_door
to_state: on
cooldown: 300
prompt: Kiểm tra ngữ cảnh liên quan và thông báo ngắn nếu cửa trước mở bất thường.
```

Rule sẽ gọi agent khi `state_changed` phù hợp. Tool policy/approval vẫn được áp dụng như chat thông thường.

## 9. Knowledge/RAG

Copy tài liệu vào:

```text
knowledge/
```

Hỗ trợ `.md`, `.txt`, `.yaml`, `.yml`, `.json`.

Bấm **Re-index knowledge** trong dashboard. RAG này là local text search bằng SQLite FTS, không gửi toàn bộ kho tài liệu vào model mỗi lượt.

Không lưu password/token trong knowledge.

## 10. Skills

Built-in skills:

- `daily-home-report`
- `energy-optimization`
- `automation-review`
- `troubleshoot-device`
- `self-maintenance`

Thêm skill bằng file Markdown trong `config/skills/`.

## 11. MCP

Cấu hình `config/mcp_servers.yaml`:

```yaml
servers:
  n8n:
    url: http://127.0.0.1:3000/mcp
    headers: {}
```

Agent có `mcp_servers`, `mcp_list_tools`, `mcp_call`.

Lưu ý: MCP ngoài là một security boundary riêng. Chỉ nối server/tool mà bạn tin cậy và tự giới hạn quyền ở phía MCP server.

## 12. SearXNG tùy chọn

Nếu bạn có SearXNG riêng:

```dotenv
SEARXNG_URL=http://127.0.0.1:8081
```

Agent sẽ có tool `web_search`. Nếu biến này rỗng, tool trả lỗi cấu hình thay vì tự truy cập Internet bằng cách khác.

## 13. Telegram tùy chọn

Điền:

```bash
printf '%s' 'BOT_TOKEN' > secrets/telegram_bot_token.txt
```

và `.env`:

```dotenv
TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321
```

Nếu allowlist để trống, gateway nhận mọi chat tới bot. Không nên để trống khi dùng thực tế.

## 14. Backup

Backup tối thiểu:

```text
data/hassmind.db
config/
knowledge/
.env
```

Không đưa thư mục `secrets/` vào Git/backup không mã hóa.

## 15. Lệnh vận hành

```bash
docker compose -f docker-stack.yml up -d --build
docker compose -f docker-stack.yml ps
docker logs -f hassmind-v1
docker compose -f docker-stack.yml restart hassmind
docker compose -f docker-stack.yml down
```

## 16. Những gì v1 cố ý KHÔNG làm

- Không có shell/SSH/Docker control tool.
- Không tự restart/update Home Assistant.
- Không tự quản lý user/token HA.
- Không tự mở lock/alarm/garage.
- Không để scheduler/event rule bypass approval.
- Không expose HA token cho model.

Đây là các giới hạn chủ ý để giữ HassMind ở vai trò home-agent có quyền mạnh nhưng vẫn có security boundary rõ ràng.

## 17. Lưu ý quyền thư mục `data/`

Container chạy bằng UID/GID `10001` thay vì root. Nếu dùng bind mount `./data:/data`, chạy một lần:

```bash
sudo chown -R 10001:10001 data
```

Hoặc dùng helper:

```bash
sudo ./setup.sh
```

## 18. Portainer Stack độc lập

Có thêm `portainer-stack.yml`. File này không ghép với HA stack và giả định image `hassmind-v1:latest` đã được build trên server:

```bash
docker build -t hassmind-v1:latest .
```

Trong Portainer -> Stacks -> Add stack, dùng `portainer-stack.yml` và khai báo Environment variables:

```text
HA_URL=http://127.0.0.1:8123
HA_TOKEN=...
HA_NOTIFY_SERVICE=notify.mobile_app_...
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=...
HASSMIND_API_TOKEN=<random 64 hex chars>
```

Cách Portainer này dùng environment variables để thuận tiện triển khai. Nếu ưu tiên secret-at-rest tốt hơn, dùng `docker-stack.yml` + `secrets/*.txt` trên filesystem.

## 19. Tool audit

Mỗi lần model gọi tool, HassMind ghi tên tool, arguments, result rút gọn hoặc error vào SQLite `tool_audit`. Xem qua API:

```text
GET /api/audit?limit=100
X-HassMind-Token: ...
```

Không dùng audit table để lưu secret; các tool mặc định không nhận HA/LLM secret làm argument.

## 20. Tích hợp các container/custom component đã rà soát (v1.1.0)

Bản v1.1.0 thêm lớp **typed integration adapters**. Các stack hiện có tiếp tục deploy độc lập; HassMind không copy database, không điều khiển Docker và không nhúng code của service khác vào process của mình.

| Dự án đã rà soát | Cách HassMind tích hợp | Endpoint/giao diện dùng | Mặc định |
|---|---|---|---|
| `gemini-fastapi-multi-account` | Dùng trực tiếp làm LLM backend OpenAI-compatible | `/v1/chat/completions`, `/v1/models` | cấu hình bằng `OPENAI_BASE_URL` |
| `camera-tts-ezviz` | HTTP adapter có API key | `/health`, `/cameras`, `/say/<id>`, `/media/<id>`, `/ptz/<id>`, `/stop/<id>`, `/jobs/<id>` | disabled |
| `facedetect` / IRIS | HTTP read adapter | `/api/health`, `/api/summary`, `/api/events`, `/api/people`, `/api/cameras` | disabled |
| `zalo-bot-server` | HTTP session client + inbound webhook | `/api/login`, `/api/accounts`, `/api/sendMessageByAccount`, `/api/webhook-accounts/*` | disabled, outbound off |
| `wyoming-vietnamese-prosody` | TCP health check + phát tiếng qua HA `tts.speak` | TCP `10300`, Home Assistant TTS | disabled |
| `EVN-CSKH-Monitor` | Gọi authenticated HA HTTP view | `/api/evncskh/*` | enabled bridge |
| `am-lich-viet-nam` | Typed HA service call có response | `am_lich_viet_nam.convert_date` | enabled bridge |
| `shopping_history` | HA WebSocket để đọc + typed services để sửa | `shopping_history/get_data`, `add_order/edit_order/delete_order` | đọc on, mutation off |
| `yt_dlp_hass` | Typed HA services | `search`, `play`, `download`, `get_job` | play on, download off |

Xem trạng thái tại tab **Integrations** hoặc:

```text
GET /api/integrations
X-HassMind-Token: ...
```

### 20.1 Dùng Gemini FastAPI Multi Account làm model cho HassMind

Không cần adapter riêng vì server Gemini đã implement OpenAI Chat Completions và tool calling. Nếu service đang publish port `8000` trên cùng host:

```dotenv
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_MODEL=<model-do-gemini-server-expose>
```

Đặt cùng API key mà Gemini server đang kiểm tra (`CONFIG_SERVER__API_KEY`) vào:

```text
secrets/openai_api_key.txt
```

Có thể kiểm tra model mà Gemini server expose bằng `GET http://127.0.0.1:8000/v1/models` với cơ chế auth tương ứng trước khi điền `OPENAI_MODEL`.

### 20.2 Camera TTS EZVIZ

```dotenv
CAMERA_TTS_ENABLED=true
CAMERA_TTS_URL=http://127.0.0.1:8124
CAMERA_TTS_ALLOW_ACTIONS=true
```

Đặt API key của camera service vào:

```text
secrets/camera_tts_api_key.txt
```

HassMind có tool đọc camera/job và các action `say`, `media`, `ptz`, `stop`. Nếu muốn chỉ quan sát trạng thái mà không cho agent phát loa/PTZ, đặt:

```dotenv
CAMERA_TTS_ALLOW_ACTIONS=false
```

### 20.3 FaceDetect / IRIS

Với stack chuẩn publish `8080:80`:

```dotenv
FACEDETECT_ENABLED=true
FACEDETECT_URL=http://127.0.0.1:8080
```

Với `portainer-stack-intel.yml` của project đã tải lên, port publish là `8181:80`, vì vậy dùng:

```dotenv
FACEDETECT_URL=http://127.0.0.1:8181
```

HassMind chỉ expose các API đọc (summary/events/people/cameras). Các trigger realtime của FaceDetect nên tiếp tục đi qua MQTT/Home Assistant webhook mà project đã hỗ trợ; cách này tránh tạo thêm một event transport song song.

### 20.4 Zalo Bot Server

Cấu hình client:

```dotenv
ZALO_ENABLED=true
ZALO_URL=http://127.0.0.1:3000
ZALO_USERNAME=admin
ZALO_DEFAULT_ACCOUNT=
ZALO_ALLOW_SEND=false
```

Đặt password web/API của Zalo server vào:

```text
secrets/zalo_password.txt
```

`ZALO_DEFAULT_ACCOUNT` có thể là `ownId` hoặc số điện thoại mà Zalo server nhận ở `accountSelection`. HassMind luôn giữ `threadId` và account ID ở dạng **string** để không mất chính xác với ID lớn.

Để agent được gửi tin chủ động, operator phải bật rõ:

```dotenv
ZALO_ALLOW_SEND=true
```

#### Webhook Zalo -> HassMind

`setup.sh` tự tạo `secrets/zalo_webhook_secret.txt`. Bật:

```dotenv
ZALO_WEBHOOK_ENABLED=true
ZALO_AUTO_REGISTER_WEBHOOK=true
ZALO_WEBHOOK_CALLBACK_BASE=http://127.0.0.1:8090
```

HassMind đăng ký thêm một destination `message` cho từng account Zalo đã login và **không xóa các webhook hiện có**. Callback thực tế có dạng:

```text
http://127.0.0.1:8090/webhooks/zalo/<random-secret>
```

Handler trả HTTP nhanh rồi mới chạy model bằng background task nội bộ, phù hợp timeout webhook ~10 giây của Zalo Bot Server.

Auto-reply được tách khỏi việc nhận webhook. Chỉ bật sau khi đã kiểm tra:

```dotenv
ZALO_ALLOW_SEND=true
ZALO_AGENT_REPLY_ENABLED=true
ZALO_AGENT_ALLOWED_THREAD_IDS=1234567890123456789,9876543210987654321
```

Auto-reply **không chạy nếu allowlist rỗng**. Khuyến nghị liệt kê rõ từng thread ID. Giá trị `*` cho phép mọi thread và chỉ nên dùng trong môi trường đã kiểm soát hoàn toàn.

### 20.5 Wyoming Vietnamese Prosody

```dotenv
WYOMING_ENABLED=true
WYOMING_HOST=127.0.0.1
WYOMING_PORT=10300
WYOMING_ALLOW_TTS=true
```

HassMind không tự implement Wyoming protocol. Nó chỉ TCP health-check port 10300; khi cần nói, agent gọi Home Assistant `tts.speak`. Nếu Home Assistant có đúng một TTS entity, hoặc đúng một entity có platform `wyoming`, HassMind tự chọn; nếu có nhiều, yêu cầu truyền `tts_entity_id` rõ ràng.

Cách này giữ Home Assistant làm voice-provider boundary và tương thích tốt hơn với Assist pipeline hiện có.

### 20.6 EVN CSKH Monitor

Không cấu hình credential EVN trong HassMind. Adapter gọi các HTTP view của custom component thông qua HA token hiện có:

```text
/api/evncskh/ping
/api/evncskh/options
/api/evncskh/summary/{account}
/api/evncskh/daily/{account}
/api/evncskh/monthly/{account}
```

Credential EVN vẫn nằm ở nơi integration hiện tại quản lý.

### 20.7 Âm lịch Việt Nam

Tool `lunar_convert_date` gọi đúng service response-only:

```text
am_lich_viet_nam.convert_date
```

HassMind dùng Home Assistant REST `return_response`, vì vậy không cần duplicate thư viện chuyển đổi âm/dương vào agent.

### 20.8 Shopping History

Đọc dữ liệu chi tiết dùng Home Assistant WebSocket command mà component đã cung cấp:

```json
{"type":"shopping_history/get_data","entry_id":"...","year":2026}
```

HassMind tự khám phá `entry_id` từ các sensor có attributes `shopping_history=true` và `config_entry_id`.

Mặc định chỉ đọc. Muốn add/edit:

```dotenv
SHOPPING_ALLOW_MUTATIONS=true
```

Muốn delete phải bật thêm lớp policy thứ hai:

```dotenv
SHOPPING_ALLOW_DELETE=true
```

### 20.9 yt-dlp Home Assistant

Search luôn là read-only. Playback và download có policy riêng:

```dotenv
YTDLP_ALLOW_PLAYBACK=true
YTDLP_ALLOW_DOWNLOADS=false
```

Các tool được model thấy: `yt_dlp_search`, `yt_dlp_play`, `yt_dlp_download`, `yt_dlp_get_job`. `download` dùng `return_response` để lấy metadata/job response từ custom component.

## 21. Security boundary của lớp integration

Các adapter mới cố ý không cung cấp một endpoint "HTTP bất kỳ" hoặc "HA custom service bất kỳ" cho model. Mỗi capability có schema cố định và whitelist field riêng. Các secret Camera TTS/Zalo được backend đọc từ Docker secrets và không được đưa vào tool arguments.

Các side effect được tách policy:

```text
CAMERA_TTS_ALLOW_ACTIONS
ZALO_ALLOW_SEND
ZALO_AGENT_REPLY_ENABLED
SHOPPING_ALLOW_MUTATIONS
SHOPPING_ALLOW_DELETE
YTDLP_ALLOW_PLAYBACK
YTDLP_ALLOW_DOWNLOADS
WYOMING_ALLOW_TTS
```

Khuyến nghị: lần deploy đầu để các cờ gửi/xóa/download/auto-reply ở `false`; kiểm tra tab **Integrations**, chạy các tool đọc, sau đó mới bật từng capability cần dùng.

## 22. Quy trình nâng cấp từ HassMind v1 cũ

1. Backup `data/hassmind.db`, `.env`, `config/`, `knowledge/` và secrets.
2. Thay code bằng bản v1.1.0 này nhưng giữ `data/` cũ.
3. Chạy `./setup.sh` để tạo thêm ba secret file mới mà không ghi đè secret cũ.
4. Merge các biến integration trong `.env.example` vào `.env` đang dùng.
5. Nếu dùng Gemini local, đổi `OPENAI_BASE_URL` sang `http://127.0.0.1:8000/v1` và dùng API key/model đúng của Gemini server.
6. Deploy lại HassMind; không cần redeploy Home Assistant hay các companion stack nếu port/API của chúng không đổi.
7. Mở tab **Integrations** và kiểm tra trạng thái từng module trước khi bật side-effect policy.

