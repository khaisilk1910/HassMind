# HassMind v1.3.2 — AI Agent riêng cho Home Assistant

## Mới trong v1.3.2

- Review changes của Knowledge chỉ giữ tối đa **4 proposal đã lỗi thời** trong hàng đợi và có vùng cuộn riêng, tránh kéo dài toàn bộ trang. Lịch sử đầy đủ vẫn nằm trong Knowledge audit.
- Chuẩn hóa thông báo theo hai kênh **Điện thoại (Home Assistant)** hoặc **Zalo** cho Approvals, Scheduler, Event rules và Knowledge monitor. Khi chọn Zalo có thể nhập `thread_id`; để trống sẽ dùng Thread ID thông báo mặc định, sau đó fallback sang Allowed thread ID đã cấu hình.
- Thông báo điện thoại được chuyển sang plain text có emoji/bullet, không còn hiện dấu Markdown như `**`, `` ` `` hoặc heading `#`. Thông báo Zalo đi qua cùng rich-text compiler với phản hồi chat Zalo.
- Scheduler và Event rules có nút **Sửa**, cho phép đổi prompt/lịch/entity/cooldown/kênh thông báo mà vẫn giữ trạng thái enabled hiện tại.
- Giữ toàn bộ sửa lỗi Knowledge v1.3.1: dry-run hiển thị vị trí xung đột chi tiết và warning conflict không khóa Re-index hợp lệ.

Đọc [changelog 1.3.2](CHANGELOG_V1.3.2.md), [QA 1.3.2](QA_V1.3.2.md) và [hướng dẫn migrate/triển khai](KNOWLEDGE_MIGRATION_VI.md). Mẫu Knowledge nằm ở `examples/knowledge/`, không tự đưa vào Knowledge đang dùng. Stack mặc định giữ Knowledge chỉ đọc; dùng override `docker-compose.knowledge-write.yml` nếu muốn apply nội dung sau phê duyệt.

## Knowledge từ 1.3.1

Semantic registry entity/area/scene/script và tài liệu reference/rules/procedures, phân biệt dữ liệu tĩnh với state HA realtime. Scan định kỳ tạo proposal/diff để người dùng Dry-run và Approve/Reject; có backup, rollback, audit và chặn stale proposal. Fuzzy/ambiguity không tự cấp quyền điều khiển. Dashboard có kết quả chi tiết, lỗi index, monitor config và editor tạo draft.


## Mới trong v1.2.9

- **Zalo mobile layout được tối ưu lại**: prompt kênh Zalo ưu tiên câu ngắn, mỗi bullet một ý, danh sách dài được tách thành bullet/numbered list lồng nhau thay vì dồn một dòng dài.
- Formatter tự **in đậm nhãn ngắn** trong list ngay cả khi model quên `**...**`, ví dụ `Nhiệt độ:`, `Cửa:`, `Quạt:`.
- Formatter tự tô màu trạng thái theo quy tắc bảo thủ khi model không chỉ định màu: xanh cho trạng thái hoạt động/tốt, cam cho mở/unavailable/cần chú ý, đỏ cho lỗi/cảnh báo/nguy hiểm. Màu model khai báo rõ luôn được ưu tiên.
- Các style trùng/chồng cùng loại được merge trước khi gửi để giảm kích thước `styles[]` và tránh vùng format dư thừa.
- Giữ nguyên UTF-16 offsets, list `lst_1/lst_2`, nested indent `ind_$`; không làm thay đổi API Zalo Server đang hoạt động ở v1.2.8.

## Mới trong v1.2.8

- **Sửa dứt điểm rich text Zalo ở transport**: HassMind không còn chỉ gửi chuỗi `#`, `**...**`, `{green}...{/green}` rồi trông chờ Zalo Server tự parse. Backend biên dịch markup thành `message.msg` sạch + `message.styles[]` đúng cấu trúc `zca-js`.
- Hỗ trợ style: bold, italic, bold+italic, underline, strike, heading `f_18/f_13`, red/orange/yellow/green, unordered/ordered list, blockquote và indent.
- Offset `start/len` của Zalo được tính theo **UTF-16 code units**, nên emoji/variation selector không làm lệch vùng in đậm/màu/list.
- Cú pháp Markdown/Zalo được loại khỏi `msg` trước khi gửi; vì vậy ngay cả khi companion server cũ từ chối `styles[]`, fallback chỉ gửi plain text sạch, không còn hiện `#`/`**` thô.
- Markdown table/fenced code/`<FollowUp>` tiếp tục được normalize trước khi compile style.

## Mới trong v1.2.7

- Sửa `ha_tts_speak` bị `ConnectionClosedError: frame exceeds limit`: bình thường không tải toàn bộ Entity Registry qua WebSocket nữa.
- Thêm trường **Home Assistant TTS entity** trong Web Admin -> Integrations -> Wyoming Vietnamese TTS. Nên cấu hình rõ, ví dụ `tts.piper`.
- `tts.speak` dùng mô hình action hiện đại: TTS entity ở `target`, `media_player_entity_id/message/...` ở `data`; transport REST chỉ flatten target tại biên API.
- `ha_call_service` hỗ trợ `target` riêng thay vì bắt model nhét tất cả vào `data`.
- Tăng trần frame WebSocket HA mặc định lên 16 MiB (có giới hạn tối đa 64 MiB), áp dụng cho cả custom WS commands và event listener.
- Thêm log `ha_tts_entity_resolved`, `ha_tts_registry_fallback`, `ha_tts_action_call` để chẩn đoán TTS.


## Mới trong v1.2.6

- Telegram now appears in Web Admin -> Integrations with enable/disable, Bot Token and Allowed Chat IDs. Runtime token is stored under `/data/secrets`; the polling supervisor hot-reloads changes without a container restart.
- Integration health now checks Telegram Bot API `getMe`, so token/network problems are visible in the same status area instead of only in Runtime Logs.
- Custom HTTP Integrations can declare fixed API Actions. Each action has method, relative path, read/write mode, request target and JSON Schema parameters. Only actions explicitly marked `agent_enabled=true` become Agent tools.
- Custom API Actions do not give the model a generic HTTP tunnel: Base URL/method/path are fixed by Web Admin; the model can only fill schema-declared arguments.
- Zalo formatting now preserves and normalizes the rich-text dialect supported by the user's Zalo Server: headings, bold/italic, underline/strike, links, color/size tags, bullets, numbering, blockquotes and indentation. Unsupported tables/fences/UI tags are converted to readable supported text.
- The Zalo channel prompt now uses green for healthy/active state, orange for attention/unavailable and red only for warnings/errors, with restrained mobile-friendly formatting.

## Mới trong v1.2.4

- Tab **Integrations** có nút **Thêm Integration** để tạo Custom HTTP Integration trực tiếp từ Web Admin. Integration mới được persist trong SQLite và xuất hiện ngay trong danh sách sau khi lưu.
- Custom Integration hỗ trợ Base URL, health path, bật/tắt, mô tả/icon, authentication kiểu Bearer token hoặc API-key header. Credential vẫn lưu riêng dưới `/data/secrets` và API chỉ trả trạng thái đã cấu hình.
- IntegrationHub tự nạp/reconfigure Custom Integration và đưa health status vào trang Integrations mà không cần sửa stack hoặc restart container sau mỗi lần chỉnh cấu hình.
- Toàn bộ card cấu hình Integration chuyển sang giao diện **thu gọn mặc định**; nhấn card để mở. Layout mới dùng 3/2/1 cột theo kích thước màn hình, tách rõ adapter tích hợp sẵn, Custom Integrations, Health Status và Effective Policy.
- Từ v1.2.6, Custom HTTP Integration có thể khai báo **API Actions / Agent Tools** cố định. Base URL, HTTP method và relative path do admin định nghĩa; model chỉ được điền các tham số đã khai báo trong JSON Schema. Action chỉ trở thành tool khi bật `agent_enabled=true`.

## Mới trong v1.2.3

- **Integrations cấu hình trực tiếp trong Web Admin**: bật/tắt, URL, policy và credential cho Camera TTS, FaceDetect, Zalo, Wyoming và HA custom components; không còn bắt buộc thêm các biến này vào stack.
- Runtime config persist trong SQLite; integration secret persist riêng dưới `/data/secrets`, không được API trả ngược về trình duyệt. Cấu hình Web Admin override stack/default và có nút khôi phục.
- IntegrationHub có thể reconfigure tại runtime nên thay đổi được áp dụng ngay; tool schema của Agent tự phản ánh integration/policy mới.
- Chat có renderer Markdown nội bộ an toàn cho heading, danh sách lồng, inline code, code block, bảng, blockquote, bold/italic và separator; tự thêm emoji ngữ cảnh cho đầu mục để nội dung dễ đọc hơn.
- Deployment stack không còn bắt buộc mount secret riêng cho Camera TTS/Zalo.

## Mới trong v1.2.2

- Sửa nút **Sao chép** Recovery Key/API token trên HTTP LAN: ưu tiên Clipboard API và tự fallback sang cơ chế copy tương thích khi trang không phải secure context.
- Chat render an toàn nội dung `**in đậm**`: bỏ dấu `**` và tô màu phần được nhấn mạnh, không dùng `innerHTML` nên không mở thêm bề mặt XSS.
- Làm rõ vòng đời secret admin: `admin_password.txt` là **bootstrap-only**; mật khẩu hiện hành chỉ tồn tại dạng Argon2id hash trong SQLite. Recovery Key xoay từ UI nằm ở `/data/secrets/admin_recovery_key`.
- Thêm cache-busting cho CSS/JS và đồng bộ version package lên `1.2.2`.

## Mới trong v1.2.1

- Sửa lỗi đổi/reset mật khẩu trả `Internal server error` khi mật khẩu mới không đạt policy.
- API giờ trả HTTP 400 kèm lý do cụ thể để UI hiển thị trực tiếp.
- Settings hiển thị rõ policy mật khẩu và kiểm tra độ dài tối thiểu ngay trên trình duyệt.

HassMind chạy **độc lập** với stack Home Assistant hiện có. Container kết nối HA qua REST/WebSocket, có dashboard quản trị riêng tại port `8090` và không cần ghép vào stack Home Assistant.

## Chức năng v1

- Agent loop + OpenAI-compatible tool calling.
- Home Assistant REST + WebSocket realtime gateway.
- Đọc state, history, entity registry và event gần đây.
- Direct-action allowlist cho các domain ít nhạy cảm.
- Sửa automation/script theo luồng proposal -> approval -> apply -> verify -> audit; có optimistic locking và rollback.
- SQLite cho chat memory, audit, events, jobs, event rules và phiên quản trị.
- Local RAG bằng SQLite FTS từ thư mục `knowledge/`.
- Skill registry từ `config/skills/*.md`.
- Scheduler và event rule mới luôn ở trạng thái disabled cho tới khi operator bật.
- External MCP client, SearXNG tùy chọn, Telegram gateway và các typed integration adapters.
- Web admin có đăng nhập bắt buộc, CSRF protection, session timeout, lockout, password recovery và quản lý phiên.

## Mới trong v1.2.0

- Khi truy cập `http://IP_SERVER:8090/`, dashboard bắt buộc đăng nhập bằng **tài khoản admin**; HassMind API token không còn dùng làm mật khẩu web.
- Tab **Settings** quản lý username, đổi mật khẩu, khôi phục mật khẩu bằng Recovery Key, phiên đăng nhập và xoay HassMind API token.
- API token được lưu ở server (`/data/secrets/hassmind_api_token` khi đổi từ UI); browser không lưu token trong `localStorage`.
- Argon2id cho mật khẩu, session token ngẫu nhiên chỉ lưu dạng SHA-256 trong SQLite, CSRF token gắn với phiên, SameSite=Strict, lockout/rate-limit và network allowlist.
- Security headers/CSP, tắt OpenAPI docs, không cache API/admin response và tắt Uvicorn server header.
- Log structured theo `request_id`, `session_id`, component và latency; tự động redact password/token/API key/Authorization/cookie/JWT và các secret đang cấu hình.
- Khi khởi động có best-effort scrub log xoay vòng và các bản ghi event/tool-audit cũ để giảm rủi ro secret còn sót từ phiên bản trước.
- Container chạy non-root UID `10001`, root filesystem read-only, `cap_drop: ALL`, `no-new-privileges`, tmpfs `/tmp`, PID limit và log rotation Docker.
- Tab **Giới thiệu** diễn giải từng tính năng; mỗi tab có hướng dẫn ngắn, cách dùng và ví dụ.
- Favicon/logo HassMind mới dùng cho browser tab và tiêu đề dashboard.

Xem chi tiết logging tại [`OBSERVABILITY.md`](OBSERVABILITY.md) và hardening tại [`SECURITY.md`](SECURITY.md).

## 1. Điều kiện

- Home Assistant đã chạy và host HassMind truy cập được, ví dụ `http://127.0.0.1:8123` khi dùng `network_mode: host`.
- Docker + Docker Compose hoặc Portainer.
- Home Assistant Long-Lived Access Token. Nếu dùng Config API cho automation/script, tài khoản tạo token cần quyền phù hợp (thường là admin).
- API key của LLM OpenAI-compatible.

Không publish port `8090` trực tiếp ra Internet. Nếu cần truy cập ngoài LAN, dùng VPN hoặc reverse proxy HTTPS và đặt `ADMIN_COOKIE_SECURE=true`.

## 2. Chuẩn bị an toàn

Khuyến nghị dùng helper vì script tạo secret bằng nguồn ngẫu nhiên mật mã, đặt quyền file và chuẩn bị thư mục đúng UID:

```bash
chmod +x setup.sh
sudo ./setup.sh
```

Sau đó điền hai secret bắt buộc:

```bash
printf '%s' 'HOME_ASSISTANT_LONG_LIVED_TOKEN' | sudo tee secrets/ha_token.txt >/dev/null
printf '%s' 'YOUR_LLM_API_KEY' | sudo tee secrets/openai_api_key.txt >/dev/null
sudo chmod 600 secrets/*.txt
```

`setup.sh` tự tạo nếu chưa tồn tại:

```text
secrets/hassmind_api_token.txt
secrets/admin_password.txt
secrets/admin_recovery_key.txt
secrets/zalo_webhook_secret.txt
```

Đọc **mật khẩu admin khởi tạo** và Recovery Key bootstrap ở lần cài đầu:

```bash
cat secrets/admin_password.txt
cat secrets/admin_recovery_key.txt
```

Hai file trên là dữ liệu **bootstrap**. Sau khi đổi mật khẩu trong Settings, `admin_password.txt` **không được cập nhật**: mật khẩu hiện hành chỉ lưu dưới dạng Argon2id hash trong SQLite nên không thể `cat` để xem lại. Nếu quên mật khẩu, dùng Recovery Key để đặt mật khẩu mới. Sau khi xoay Recovery Key từ UI, khóa hiện hành được lưu ở `/data/secrets/admin_recovery_key`; với stack mount `/opt/hassmind/data:/data`, đọc bằng:

```bash
sudo cat /opt/hassmind/data/secrets/admin_recovery_key
```

`/opt/hassmind/secrets/admin_recovery_key.txt` vẫn là khóa bootstrap cũ và sẽ không còn hợp lệ sau khi rotate.

Sửa `.env` tối thiểu:

```dotenv
HA_URL=http://127.0.0.1:8123
HA_NOTIFY_SERVICE=notify.mobile_app_your_phone
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=your_model
```

`OPENAI_MODEL` phải là model/provider thực sự hỗ trợ tool/function calling.

## 3. Deploy stack riêng

### Docker Compose

```bash
docker compose -f docker-stack.yml up -d --build
```

Kiểm tra:

```bash
docker compose -f docker-stack.yml ps
docker logs --tail 100 hassmind-v1
```

### Portainer

Khuyến nghị deploy từ Git repository để Portainer lấy được toàn bộ build context. Nếu chỉ dùng Web editor, build image trước:

```bash
docker build -t hassmind-v1:latest .
```

rồi deploy `portainer-stack.yml`.

**Lưu ý bảo mật:** `docker-stack.yml`/`docker-compose.yml` dùng Docker secrets là lựa chọn ưu tiên. `portainer-stack.yml` nhận secret qua environment variables để thuận tiện nhưng secret có thể xuất hiện trong metadata của container cho người có quyền Docker/Portainer.

## 4. Đăng nhập web và API token

Mở:

```text
http://IP_SERVER:8090/
```

Bạn sẽ được chuyển tới `/login`. Mặc định username là:

```text
admin
```

Mật khẩu ban đầu là nội dung `secrets/admin_password.txt` nếu bạn deploy bằng Compose/Docker secrets. Sau lần đăng nhập đầu tiên, vào **Settings -> Tài khoản admin** để đổi mật khẩu. Từ thời điểm đó file bootstrap này vẫn giữ giá trị cũ và **không thể dùng để xem mật khẩu hiện hành**, vì HassMind chỉ lưu Argon2id hash trong SQLite.

Nếu quên mật khẩu, chọn **Quên mật khẩu?** trên trang login và dùng Recovery Key. Ban đầu khóa nằm trong `secrets/admin_recovery_key.txt`; nếu đã xoay tại **Settings -> Recovery Key** thì khóa runtime mới trong `/data/secrets/admin_recovery_key` có ưu tiên cao hơn. Với mount `/opt/hassmind/data:/data`, khóa hiện hành sau rotate đọc bằng `sudo cat /opt/hassmind/data/secrets/admin_recovery_key`. Khôi phục thành công sẽ thu hồi toàn bộ phiên cũ.

Trong **Settings -> Recovery Key**, admin có thể tạo khóa mới sau khi xác nhận mật khẩu hiện tại. Khóa mới chỉ hiển thị một lần; hãy lưu ngay ở nơi offline/password manager. Khóa cũ bị vô hiệu ngay sau khi xoay.

HassMind API token dành cho API/integration ngoài dashboard. Xem/xoay cấu hình tại **Settings -> HassMind API token**. Khi chọn **Tạo token ngẫu nhiên**, token mới chỉ hiện một lần; lưu ngay nếu client ngoài cần dùng. Ví dụ gọi API:

```bash
curl -H "X-HassMind-Token: $(cat secrets/hassmind_api_token.txt)" http://IP_SERVER:8090/api/status
```

Nếu bạn đã xoay token trong Settings, token runtime tại `/data/secrets/hassmind_api_token` có ưu tiên cao hơn Docker secret ban đầu.

Health endpoint không yêu cầu đăng nhập:

```text
http://IP_SERVER:8090/health
```

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

Secret nên backup **mã hóa** và tách khỏi source code. Đặc biệt phải giữ `admin_recovery_key`; nếu mất cả mật khẩu admin và Recovery Key thì cơ chế khôi phục web không thể xác minh bạn.

Không commit các mục sau vào Git:

```text
.env
secrets/*.txt
data/
```

`.gitignore` và `.dockerignore` đã chặn các đường dẫn này, nhưng vẫn cần kiểm tra repository trước khi push.

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

Có `portainer-stack.yml` và `portainer-stack-opt.yml`. Hai file giữ container non-root, read-only root filesystem, drop capabilities, `no-new-privileges`, PID limit và `/tmp` tmpfs.

Nếu dùng `portainer-stack.yml`, build image trước:

```bash
docker build -t hassmind-v1:latest .
```

Các biến bắt buộc/quan trọng trong Portainer:

```text
HA_TOKEN=...
OPENAI_API_KEY=...
OPENAI_MODEL=...
HASSMIND_API_TOKEN=<random >= 32 chars>
ADMIN_BOOTSTRAP_PASSWORD=<strong password >= 14 chars>
ADMIN_RECOVERY_KEY=<random recovery key>
```

Dùng HTTP LAN trực tiếp thì giữ:

```text
ADMIN_COOKIE_SECURE=false
```

Khi reverse proxy đã phục vụ HTTPS đúng cách, chuyển thành:

```text
ADMIN_COOKIE_SECURE=true
```

Portainer environment variables thuận tiện nhưng không mạnh bằng Docker secrets về secret-at-rest. Nếu mục tiêu là hardening tối đa, ưu tiên `docker-stack.yml`/`docker-compose.yml` với `secrets/*.txt`.

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

### 20.2 Cấu hình Integrations từ Web Admin

Từ v1.2.3, các integration đã được HassMind hỗ trợ **không còn bắt buộc khai báo trong stack**. Sau khi deploy core HassMind, mở tab **Integrations** để cấu hình và bấm **Lưu & áp dụng**.

Cấu hình không nhạy cảm được lưu trong bảng `integration_settings` của `/data/hassmind.db`. Credential nhập từ Web Admin được lưu riêng dưới `/data/secrets/` với quyền runtime của container và **không được API trả ngược ra trình duyệt**.

Thứ tự ưu tiên là:

1. Web Admin runtime override.
2. Docker secret / environment cũ nếu bạn vẫn đang dùng.
3. Giá trị mặc định trong code.

Nút **Khôi phục stack/default** xóa runtime override của integration đó và quay về nguồn cũ. Vì vậy nâng cấp từ cấu hình `.env` hiện tại không bị mất tương thích.

#### Thêm Custom HTTP Integration

Từ v1.2.4, nhấn **Thêm Integration** ở đầu trang để tạo một Integration mới mà không sửa stack. Các trường chính gồm tên, ID, Base URL, health path và authentication. ID có thể để trống để HassMind tự sinh từ tên.

Custom Integration được lưu trong bảng `custom_integrations`; credential nằm trong `/data/secrets/integration_custom_<id>_secret`. Khi bật Integration, HassMind gọi `GET <base_url><health_path>` để hiển thị trạng thái kết nối. Có thể sửa, bật/tắt hoặc xóa ngay trên Web Admin.

Đây là lớp **health/config registry**, không phải generic action bridge. Nếu muốn AI gọi chức năng nghiệp vụ của service mới, hãy thêm typed adapter/tool với schema và policy rõ ràng thay vì cho model gọi HTTP tùy ý.

### 20.3 Camera TTS EZVIZ

Trong **Integrations → Camera TTS EZVIZ**, cấu hình Base URL, API key, bật integration và policy cho phép TTS/media/PTZ. Default URL là `http://127.0.0.1:8124`. Nếu chỉ muốn agent đọc trạng thái, tắt **Cho phép TTS/media/PTZ**.

### 20.4 FaceDetect / IRIS

Trong **Integrations → IRIS FaceDetect**, bật integration và nhập Base URL. Với stack Intel thường dùng `http://127.0.0.1:8181`; nếu service publish port khác thì nhập đúng port thực tế. HassMind chỉ expose các API đọc summary/events/people/cameras.

### 20.5 Zalo Bot Server và Wyoming

**Zalo Bot Server:** nhập URL, username/password, policy gửi tin, webhook và allowlist thread ngay trong Web Admin. Password và webhook secret được giữ trong `/data/secrets`. Auto-reply vẫn yêu cầu đồng thời bật policy gửi, agent reply và allowlist thread.

**Wyoming Vietnamese TTS:** nhập host/port, bật integration và policy TTS trong Web Admin. HassMind chỉ TCP health-check Wyoming; phát giọng nói vẫn đi qua Home Assistant `tts.speak`.

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

1. Backup `data/hassmind.db`, `.env`, `config/`, `knowledge/` và secrets hiện có.
2. Thay code bằng bản v1.2.9 này nhưng giữ `data/` cũ.
3. Chạy `sudo ./setup.sh`. Script chỉ tạo core secret còn thiếu, không ghi đè secret đang có. Nếu phát hiện Camera TTS/Zalo/Telegram secret từ bản cũ, script tự migrate một lần sang `data/secrets/integration_*`; runtime secret mới có sẵn sẽ không bị ghi đè. Integration credential cũng có thể nhập/sửa sau trong Web Admin.
4. Merge các biến core mới từ `.env.example` vào `.env`. Không cần đưa Camera TTS/FaceDetect/Zalo/Wyoming vào stack nếu sẽ quản lý bằng Web Admin.
5. Deploy lại HassMind. Lần startup đầu sẽ tạo bảng admin/session mới, bootstrap tài khoản admin và best-effort scrub event/tool-audit + log file cũ.
6. Truy cập `/`, đăng nhập bằng password trong `secrets/admin_password.txt`, sau đó đổi mật khẩu ở **Settings**.
7. Mở **Settings** kiểm tra `Allowed networks`, `Cookie Secure`, trạng thái redaction, API token và Recovery Key source. Nếu muốn loại bỏ dependence vào Recovery Key bootstrap, xoay Recovery Key một lần và lưu khóa mới an toàn.
8. Mở **Integrations** và kiểm tra từng module trước khi bật side-effect policy.

**Quan trọng khi nâng cấp từ bản logging cũ:** cơ chế scrub có thể che các secret còn nhận dạng được hoặc vẫn đang cấu hình, nhưng không thể chứng minh đã nhận ra mọi secret tùy ý từng xuất hiện trong log cũ. Nếu trước đây từng bật log nội dung hoặc nghi ngờ token bị ghi thô, hãy archive mã hóa để điều tra hoặc xóa `data/logs/hassmind.log*` sau khi đã lấy thông tin cần thiết, rồi xoay các credential liên quan.
