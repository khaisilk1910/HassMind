# HassMind v1.2.3 — QA report

Ngày rà soát: 2026-10-04.

## Phạm vi

- Runtime Integration configuration trong Web Admin.
- SQLite migration `integration_settings`.
- Runtime secret storage và redaction.
- Hot reconfigure IntegrationHub/Zalo registration task.
- Rich Markdown renderer + semantic emoji cho Chat.
- Deployment YAML không còn yêu cầu integration-specific secrets/env.

## Static validation — PASS

- `python3 -m compileall -q app`
- `node --check static/app.js`
- `node --check static/login.js`
- `sh -n setup.sh`
- Parse YAML bằng PyYAML:
  - `docker-compose.yml`
  - `docker-stack.yml`
  - `portainer-stack.yml`
  - `portainer-stack-opt.yml`
  - `config/mcp_servers.yaml`
- Kiểm tra toàn bộ literal `$('<id>')` trong `static/app.js` đều tồn tại trong `static/index.html`.
- Không có duplicate static DOM id.

## Runtime Integration config smoke test — PASS

Đã test với SQLite/runtime-secret tạm:

- Save Camera TTS config tạo runtime override.
- URL được normalize bỏ `/` cuối.
- Boolean policy được áp dụng đúng vào `settings`.
- API config view chỉ báo secret `configured`, giá trị trả về rỗng.
- Secret không xuất hiện trong SQLite file.
- Secret được ghi dưới `/data/secrets` tương đương và mode `0600`.
- `load_runtime_integration_overrides()` khôi phục config sau khi mô phỏng restart.
- Reset xóa DB override + runtime secret và quay về stack/default.

## IntegrationHub hot reconfigure — PASS

- Khởi tạo disabled → client không tồn tại.
- Bật FaceDetect runtime → `reconfigure()` tạo client mới.
- Tắt lại → client được đóng và reference trở về `None`.
- `ToolRuntime` vẫn dùng cùng `IntegrationHub` object nên không cần rebuild Agent.

## Main endpoint smoke test — PASS

Dùng stub tối thiểu cho `openai`/`mcp` vì QA host không cài hai package này:

- `PUT /api/integrations/config/facedetect` logic save + reconfigure thành công.
- Cấu hình persist vào `integration_settings`.
- Health-check unreachable được trả thành status lỗi, không làm mất config.
- `DELETE /api/integrations/config/facedetect` reset + reconfigure thành công.

## Markdown renderer — PASS

Mẫu test chứa đúng cấu trúc người dùng báo lỗi:

- `###` heading
- `*` list và nested list
- `**bold**`
- `` `entity_id` ``
- `---`
- `&#x20;`

Kết quả:

- Không còn marker `###`, `**`, `&#x20;` trong text hiển thị.
- DOM có heading/list/strong/code/hr đúng loại.
- Emoji ngữ cảnh được thêm cho heading/bullet phù hợp.

## XSS safety — PASS

Test nội dung có `<img onerror=...>` và `<script>...</script>` trong Chat:

- Không tạo DOM `IMG` hoặc `SCRIPT` từ nội dung model.
- Nội dung HTML nguy hiểm chỉ tồn tại như text/code.
- Renderer không dùng `innerHTML` cho câu trả lời Chat.

## Deployment review — PASS

`setup.sh` đã được test migration secret legacy:

- Nếu `secrets/camera_tts_api_key.txt`, `secrets/zalo_password.txt` hoặc `secrets/zalo_webhook_secret.txt` cũ có dữ liệu và runtime secret mới chưa tồn tại, script copy một lần sang `data/secrets/integration_*`.
- Runtime secret hiện có không bị ghi đè.
- File đích được đặt mode `0600`.

Các file stack mặc định không còn khai báo/mount bắt buộc:

- `camera_tts_api_key`
- `zalo_password`
- `zalo_webhook_secret`
- các biến Camera TTS / FaceDetect / Zalo / Wyoming / Shopping / yt-dlp trong Portainer stack

Legacy environment/Docker-secret vẫn được backend hỗ trợ nếu operator tự cấu hình.

## Giới hạn QA

- QA host không có container companion thật nên không test end-to-end Camera TTS/FaceDetect/Zalo/Wyoming qua network thật.
- QA host không cài `openai` và `mcp`; import endpoint smoke test dùng stub. Docker image vẫn cài dependency thật từ `requirements.txt`.
- Việc thêm **một loại adapter hoàn toàn mới** vẫn cần code client/tool tương ứng. Web Admin hiện loại bỏ nhu cầu sửa stack cho các adapter đã được HassMind hỗ trợ và UI được sinh từ catalog để việc bổ sung adapter code-backed sau này đơn giản hơn.
