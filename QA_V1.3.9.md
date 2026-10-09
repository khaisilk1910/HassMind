# QA HassMind v1.3.9

## Phạm vi rà soát

- Scenario Dry Run backend: chọn skill cố định, thực thi read-only evidence, suppress action, policy preview và response preview.
- Boundary side-effect: Home Assistant service, TTS/Zalo/config/scheduler/event/MCP/custom integrations.
- Custom Integration edge case: `mode=read` nhưng HTTP method không phải GET phải bị suppress.
- Skills UI: selector, prompt mẫu, request CSRF, kết quả `NO — Dry Run` và planned actions.
- Chat UI: vùng câu hỏi mẫu thu gọn, tìm kiếm và đủ 21 built-in skills.
- Regression toàn bộ Python/JavaScript hiện có, validation skills, syntax và stack YAML.

## Kết quả

- Full Python suite với import-only stubs ngoài source tree: **173 passed + 12 subtests passed**.
- JavaScript UI suite: **29/29 PASS**.
- Skills focused suite (`management + layout + scenario dry-run + prompt library`): **15/15 PASS**.
- Scenario Dry Run backend: **3/3 PASS**, gồm allowed service bị suppress, blocked service bị suppress và custom read-mode POST bị suppress.
- `node --check static/app.js` và `node --check static/login.js`: **PASS**.
- `python -m compileall -q app`: **PASS**.
- 21 built-in Home Assistant skills: **21 valid, 0 invalid, 0 warning**.
- Docker/Swarm/Portainer/Knowledge override YAML parse: **PASS**.

## Kiểm tra an toàn Dry Run

- Read-only Home Assistant/Knowledge tools có thể chạy để lấy evidence thực tế.
- Action tools không đi vào `ToolRuntime.call`; response luôn báo `execution.actions_executed = 0`.
- `ha_call_service` vẫn được policy-check để preview allowed/blocked nhưng không bao giờ được execute trong Dry Run.
- Custom HTTP tool chỉ được coi là safe read khi `mode=read` và `method=GET`; non-GET luôn bị intercept.
- API Dry Run là admin-only và dùng CSRF như các mutation endpoint khác; mỗi lượt có audit/log.

## Ghi chú môi trường QA

Runner QA không có package `openai` và `mcp` cài sẵn. Full Python suite sử dụng import-only stubs tạm thời ở `/tmp/hassmind_stubs`, nằm ngoài source tree và không được đóng gói. Image HassMind vẫn cài dependency thật từ `requirements.txt` khi build.
