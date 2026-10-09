# QA — HassMind 1.3.0 Knowledge

Kiểm thử ngày 04/10/2026. Source đầu vào: `hassmind-v1.2.9-reviewed.zip`; gói giao: `hassmind-v1.3.0-knowledge-reviewed.zip`. Không thay đổi file đồng bộ của ChatGPT project.

## Kết quả

**125 test Python PASS**, không fail/skip, gồm 34 test cũ và 91 test mới. Runner Python có một test gọi bộ UI **17 test JavaScript PASS**; 17 bài này cũng đã chạy riêng bằng Node. Lượt tổng hợp cuối chạy trong khoảng 26 giây tại môi trường QA, không phải cam kết thời gian cho máy triển khai.

| Bộ test | Số test | Nội dung |
|---|---:|---|
| test_custom_integration_actions | 4 | Tools opt-in, fixed paths, GET/POST payload cũ |
| test_fast_state_tools | 3 | Search state tiếng Việt, domain/state filters |
| test_ha_actions_and_tts | 8 | Target flattening, TTS discovery, policy transport |
| test_ha_state_cache | 2 | Reuse/event update/cache invalidation |
| test_message_format | 15 | Định dạng Zalo, Unicode/offsets |
| test_zalo_transport | 2 | Rich text/plain fallback |
| test_knowledge_registry | 25 | Bảy loại record, legacy formats, exact/alias/name/area-domain/fuzzy, ambiguity, inheritance, schema/security, transactional index, FTS, stale control gate |
| test_knowledge_routing | 25 | Prompt trust boundary, context isolation, copied ID/name bypass, fuzzy/low confidence, broad/empty targets, HA/TTS/playback checks |
| test_knowledge_governance | 21 | Draft/diff/dry-run/apply/reject, whole-tree stale hash, content/size validation, scan/dedup, notification, HA outage, audit/backup |
| test_knowledge_transactions | 11 | Partial failure, concurrent operator edits, compensation, crash journals, recovery_required, byte-exact rollback, desired scene/static settings |
| test_knowledge_api | 8 | Search compatibility/filter metadata, session/CSRF, API-token rejection for decisions, 404/409/422, file editor, config/status/audit, startup/shutdown |
| test_knowledge_ui | 1 | Python wrapper của 17 test Node |

UI JavaScript kiểm tra escaping/XSS ở mọi metadata/diff/error, filters, index manifest/errors, CSRF, dry-run gate, stale approve, Reject/Rollback, editor expected_hash, config bounds, source reload failure và stale-index warning.

## Syntax, import và startup

- `python -m compileall -q app tests`: PASS.
- Import toàn bộ **30 app modules**, gồm `app.main`, version 1.3.0: PASS.
- `node --check static/app.js` và `static/login.js`: PASS.
- `pip check`: không phát hiện requirement bị hỏng.
- TestClient startup/shutdown chạy lifespan thật với HA/IntegrationHub/Agent giả lập; DB/auth init, Knowledge recovery, background monitor, health và authenticated Knowledge status hoạt động; tất cả task kết thúc khi shutdown.
- YAML các deployment stack và Compose override: parse PASS. Sample: **8 file, 16 record, đủ 7 loại, không schema error**. File per-area là phương án thay thế catalog phẳng.
- Browser smoke dùng fixture với giao diện thật: Knowledge tab, search metadata, review unified diff, disabled Approve trước dry-run, enabled sau dry-run; desktop và mobile 390×844 không tràn ngang/console error. Sau thêm gate stale, test Node kiểm tra cảnh báo tương ứng.
- Benchmark cục bộ 1.000 entity + 1 rules record: khoảng 83–134 ms/query với normalized FTS. Không bao gồm thời gian HA hoặc LLM và không thay thế benchmark ở nhà.

## Môi trường và cách chạy lại

Windows, Python 3.12.14; dependency chính được ghi trong `requirements-tested.txt`: FastAPI 0.142.2, Starlette 1.7.0, httpx 0.28.1, OpenAI 2.54.0, MCP 1.30.0, Pydantic 2.13.5, PyYAML 6.0.3, websockets 15.0.1. File constraints là lựa chọn tái lập các package chính đã test, không phải lock đầy đủ các dependency gián tiếp hay chứng nhận image Linux.

```sh
python -m venv .venv
# Activate the venv for your platform.
python -m pip install -r requirements.txt -c requirements-tested.txt
# Windows zoneinfo support if needed:
python -m pip install tzdata -c requirements-tested.txt
python -m unittest discover -s tests -v
node --test tests/test_knowledge_ui.js
python -m compileall -q app tests
node --check static/app.js
node --check static/login.js
python -m pip check
```

Node cần có trong PATH hoặc đặt `NODE_BINARY` tới executable để wrapper Python không skip UI. Tests tạo DB/Knowledge tạm và mock HA/LLM; không cần token HA thật. Một số test cố tình sinh lỗi DB/index/tool arguments để kiểm tra recovery; log ERROR trong tình huống đó là kết quả mong đợi khi assertion PASS.

Starlette đã phát một deprecation warning về TestClient sử dụng httpx; suite hiện tại vẫn chạy thành công. Không thay dependency transport chỉ để loại warning trong bản Knowledge này.

## Giới hạn cần kiểm tra khi triển khai

- **Chưa build/chạy Docker**, máy QA không có Docker CLI. Chỉ kiểm tra cú pháp YAML, source/import và startup giả lập.
- **Chưa kết nối HA/LLM thật hoặc điều khiển thiết bị thật**. Cần kiểm tra registry permission, notify service, live-state validation, service behavior và prompt trên model đang dùng.
- Cần mount Knowledge `rw` và quyền UID 10001 để apply; default `ro` vẫn hỗ trợ read/scan/dry-run/reindex. Read-only/partial-write failures được mô phỏng trong test, chưa kiểm tra mount container thật.
- Chỉ một tiến trình/replica nên ghi cùng kho. Per-file hash + atomic replace không phải khóa hệ điều hành đối với editor ngoài ứng dụng; tránh sửa file đồng thời với apply/rollback. Journal phát hiện các external edits đã được kiểm tra trong test và giữ trạng thái recovery_required thay vì overwrite.
- Fuzzy chỉ dùng gợi ý/tra cứu; confidence là điểm quy tắc. Alias cũ từ index lỗi/stale không tự cấp quyền điều khiển. Explicit entity ID do người dùng nhập vẫn theo policy HA cũ.
- Scan phát hiện drift theo interval; chưa phát hiện cho đến lần scan tiếp theo nếu file sửa giữa các scan. Re-index là thao tác được người dùng yêu cầu. Không tự đổi entity_id theo fuzzy hoặc nâng cấp schema không biết.
- Không chạy test tải lớn/sự cố mất điện thật, kiểm thử mọi plugin MCP bên ngoài hoặc toàn bộ tính năng dashboard không liên quan. Bộ test cũ và các đường Knowledge/HA liên quan đã được chạy.

Xem `KNOWLEDGE_MIGRATION_VI.md` cho cấu hình, quyền, backup và quy trình xử lý recovery.
