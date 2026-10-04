# Knowledge / local RAG — triển khai và migrate lên 1.3.0

Knowledge là semantic registry và tài liệu tĩnh. Entity/area/scene/script giúp xác định thiết bị; reference/rules/procedures giúp tra cứu. Trạng thái bật/tắt, nhiệt độ hiện tại, pin, công suất và trạng thái media phải đọc từ Home Assistant. Không đưa mật khẩu/token vào Knowledge.

## Nâng cấp từ 1.2.9

1. Dừng HassMind và backup `data/`, `knowledge/`, `.env`, `config/` và secrets. Backup cả DB trước khi thay đổi schema; nếu DB đang chạy, dùng SQLite backup API hoặc dừng dịch vụ trước khi sao chép để tránh thiếu WAL.
2. Thay source bằng bản 1.3.0, giữ các thư mục dữ liệu và cấu hình hiện có. Build lại image. Không ghi đè Knowledge của nhà bằng sample.
3. Các bảng Knowledge mới tự tạo khi khởi động; các bảng/chunk cũ vẫn đọc được. Mở Knowledge → Scan Knowledge → xem lỗi/đề xuất → Re-index để chuyển sang registry mới. Re-index là thao tác chủ động thay đổi index, không sửa nội dung tài liệu.
4. `.md/.txt/.yaml/.yml/.json` vẫn hỗ trợ. Văn bản cũ được tìm như reference; catalog có cấu trúc được index từng record. Markdown có YAML frontmatter hỗ trợ `kind`, `name`, `aliases` và metadata. YAML/JSON thuần không thuộc schema registry vẫn được tìm như tài liệu reference.
5. Kiểm tra các cách gọi thực tế: alias chính xác, tên thiết bị, area + domain và câu nhập nhằng. Thay toàn bộ entity ID mẫu bằng entity thật trong HA trước khi sử dụng.

Schema lỗi sẽ giữ index thành công trước đó và hiển thị `retained_previous`, lỗi và thời điểm index. Khi chưa Re-index, index cũ có thể chưa phản ánh nội dung mới. Scan định kỳ chỉ kiểm tra và tạo proposal; không tự thay file hoặc tự đưa nội dung mới vào index.

## Sample

Mẫu nằm ở `examples/knowledge/`, ngoài thư mục đang index. Copy các file cần thiết sau khi sửa entity ID và area ID theo nhà của bạn. `20-entities.yaml` là catalog, `10-areas.yaml` là danh mục phòng, `30-scenes-scripts.yaml` chứa scene/script, các file còn lại là reference/rules/procedures. Mẫu `areas/bedroom.yaml` minh họa area kế thừa trong một file theo phòng; đây là phương án thay thế catalog phẳng, tránh copy trùng hai bản định nghĩa cùng entity.

```yaml
schema_version: 1
entities:
  - entity_id: climate.may_lanh_phong_ngu
    name: Máy lạnh phòng ngủ
    aliases: [điều hòa phòng ngủ, máy lạnh ngủ]
    area_id: bedroom
    area: Phòng ngủ
    domain: climate
    capabilities: [power, temperature, hvac_mode]
    preferred_actions:
      set_temperature: climate.set_temperature
    static_limits:
      temperature: {min: 24, max: 27}
    notes: Trạng thái thực tế phải đọc từ Home Assistant.
```

`static_limits`, `capabilities`, `preferred_actions`, `defaults`, `parameters`, `presets`, `actions`, `service_data` mô tả cấu hình/mục tiêu tĩnh và được giữ. Snapshot realtime trong entity record được loại khỏi nội dung index và báo cảnh báo; file gốc giữ nguyên cho đến khi người dùng duyệt diff. Scene/script có thể chứa thông số mong muốn như brightness/temperature; không coi các thông số mục tiêu đó là state hiện tại. Nội dung văn bản cũ có thể nhắc trạng thái lịch sử; prompt bắt buộc chỉ dùng HA để trả lời trạng thái hiện tại.

## Resolution và quyền điều khiển

Ưu tiên: entity_id chính xác → alias chính xác → name chính xác → area + domain → fuzzy. Tên tiếng Việt được chuẩn hóa dấu và chữ hoa/thường. Kết quả có confidence, match_type, candidates, source và safe_for_control. Confidence là điểm quy tắc, không phải xác suất đã hiệu chuẩn hay vector similarity.

Fuzzy, nhiều candidate hoặc metadata mâu thuẫn phải hỏi lại. Agent không được lấy ID từ kết quả fuzzy rồi gọi resolver lại để tự cấp quyền điều khiển. Provenance nằm riêng trong từng lượt chat và chặn ở tool dispatch lẫn HA service boundary, kể cả TTS/playback. Index retained/error hoặc fingerprint mới nhất từ Scan khác index cũng không tự cấp quyền điều khiển theo alias cũ; xem `index_warning`, sửa và Re-index. Entity ID do người dùng nhập trực tiếp vẫn giữ hành vi cũ. Các domain allow/deny và approval cho automation/script cũ không được nới quyền. Trước khi dùng entity đã resolve từ catalog, HA kiểm tra state hiện tại; sau service call agent cần đọc lại state, không suy ra thành công chỉ từ HTTP 200.

## Scan và proposal

Monitor mặc định quét mỗi 300 giây, gồm file mới/thay đổi/xóa, schema, alias/domain/area mâu thuẫn và đối chiếu HA entity/area/device registry. HA offline hoặc không có quyền registry: ghi `ha_error`, hoãn kiểm tra unresolved; không tự kết luận tất cả entity đã bị xóa.

Các đề xuất tự tạo gồm refresh index sau thay đổi file; loại snapshot realtime và điền/sửa domain theo entity ID; các vấn đề cần người dùng sửa thủ công. Không đoán entity rename từ fuzzy và không tự sửa alias/area theo HA. Diff YAML có thể thay đổi định dạng hoặc comment do serializer: xem toàn bộ diff trước khi Approve.

Luồng UI: Scan Knowledge → Review changes → xem diff → Dry-run → Approve hoặc Reject. Proposal dạng review chỉ liệt kê vấn đề, không được apply: dùng form **Tạo đề xuất sửa nội dung**, tải file nguồn, sửa nội dung và lý do, tạo draft rồi dry-run/approve riêng. Tải nguồn giữ sha256 để không tạo draft trên bản đã stale. Tạo file mới bằng đường dẫn tương đối, bỏ bước tải nguồn.

Approve kiểm tra lại fingerprint toàn kho, từng file hash, schema và xung đột prospective catalog; dry-run thành công trước đó không bỏ qua kiểm tra này. Nếu file bất kỳ đã đổi, proposal stale bị chặn; scan và tạo đề xuất mới. Reject được lưu trong DB, đề xuất tự động y hệt không được tạo lại cho cùng phiên bản nội dung.

Approve/Reject/Rollback/config/draft cần phiên admin và CSRF. API token chỉ được đọc, scan, dry-run và re-index theo tương thích API cũ. Agent không được cung cấp tool approve/apply. HA notification chỉ hướng người dùng mở Web Admin để duyệt, không tự approve từ nội dung chat hoặc sự kiện HA.

## Cấu hình và quyền ghi

```dotenv
KNOWLEDGE_DIR=/knowledge
KNOWLEDGE_MONITOR_ENABLED=true
KNOWLEDGE_SCAN_INTERVAL_SECONDS=300
KNOWLEDGE_NOTIFY_ENABLED=true
KNOWLEDGE_MAX_FILE_BYTES=2097152
HA_NOTIFY_SERVICE=notify.mobile_app_your_phone
```

Interval hợp lệ 30–86400 giây; mỗi file mặc định tối đa 2 MiB, tổng kho tối đa 32 MiB và 2000 file. Web Admin lưu monitor config trong SQLite và ưu tiên giá trị đã lưu so với environment mặc định; thay đổi qua UI nếu đã lưu cấu hình. Khi tắt monitor, Scan thủ công vẫn chạy. Notification gửi khi có thay đổi/phát hiện mới; trạng thái không đổi không gửi nhắc lặp. UI vẫn có đề xuất khi không cấu hình HA_NOTIFY_SERVICE. Lỗi gửi thông báo được ghi audit và hiển thị ở trạng thái scan; có thể scan thủ công sau khi sửa cấu hình.

Các stack cũ mount `/knowledge:ro` theo mặc định. Chế độ này vẫn tìm, scan, dry-run và re-index được vì index/backup nằm trong `/data`; apply nội dung cần mount Knowledge `rw` và quyền UID/GID 10001 ghi. Docker Compose có override tùy chọn:

```sh
docker compose -f docker-compose.yml -f docker-compose.knowledge-write.yml up -d --build
```

Với Portainer/Swarm, đổi đúng mount Knowledge từ `:ro` sang `:rw` khi muốn dùng apply đã duyệt; giữ các mount config/secret khác như cũ. Trên Linux, cấp quyền cho UID 10001 ở thư mục Knowledge và data, không mở quyền ghi toàn hệ thống. Symlink/junction, hidden path, path traversal và extension ngoài danh sách bị chặn. Dùng một tiến trình HassMind cho cùng Knowledge/SQLite; không chạy nhiều replica cùng ghi file. Hash được kiểm tra trước mỗi ghi và ghi file bằng replace nguyên tử; không có khóa filesystem liên tiến trình đối với editor ngoài ứng dụng, nên tránh chỉnh file đồng thời với apply/rollback.

## Backup, rollback và khôi phục

Backup nguyên byte từng file lưu trong bảng proposal SQLite trước khi apply, cùng trạng thái `applying`. Rollback chỉ cho proposal content đã applied, khôi phục đúng byte gốc hoặc xóa file đã tạo; reindex proposal không có rollback nội dung. Rollback chặn khi file đã sửa sau apply. Lỗi ghi nhiều file sẽ bù lại các file đã ghi nếu hash vẫn phù hợp, không ghi đè sửa đổi mới của người vận hành.

Startup kiểm tra journal `applying/rolling_back`. Nếu byte file thuộc trước/sau proposal và index khôi phục thành công, hoàn tác thao tác bị gián đoạn. Nếu có external edit, quyền ghi lỗi hoặc index lỗi, giữ backup và đánh dấu `recovery_required`. UI hiển thị số proposal cần xử lý. Mở proposal + audit, backup DB/Knowledge trước khi phục hồi thủ công; không tự xóa DB để mất journal. Khôi phục đúng file từ backup quản trị hoặc tạo draft mới trên nội dung hiện tại. Với việc rollback source về 1.2.9, nên phục hồi snapshot DB/Knowledge trước nâng cấp thay vì giả định schema downgrade tự động.

Audit lưu action, người duyệt, thời điểm, file path, validation và trạng thái. Log vận hành tránh in toàn nội dung file/diff; proposal và backup chứa tài liệu riêng, cần bảo vệ thư mục `/data` và chỉ cấp quyền quản trị cho người tin cậy. `/health` kiểm tra liveness; `/api/knowledge/status` và `/api/diagnostics` cung cấp tình trạng index/monitor/khôi phục.

## API

| Endpoint | Tác dụng |
|---|---|
| GET /api/knowledge/search?q=...&area=...&domain=...&type=entity | List kết quả, giữ trường cũ và bổ sung metadata/score |
| GET /api/knowledge/resolve?q=... | Identity/confidence/ambiguity/safe_for_control |
| POST /api/knowledge/reindex | Index transactional, không sửa file |
| GET /api/knowledge/status | Index, manifest, lỗi, config, scan, pending/recovery |
| POST /api/knowledge/scan | Kiểm tra và tạo proposal, không apply |
| GET /api/knowledge/proposals và /{id} | Xem đề xuất/diff |
| POST /api/knowledge/proposals | Admin tạo content draft với reason và changes |
| POST /api/knowledge/proposals/{id}/dry-run | Kiểm tra không ghi file |
| POST /api/knowledge/proposals/{id}/approve, /reject, /rollback | Admin quyết định hoặc rollback |
| GET /api/knowledge/file?path=... | Admin tải source/hash để sửa draft |
| PATCH /api/knowledge/config | Admin lưu cấu hình monitor |
| GET /api/knowledge/audit | Audit riêng cho Knowledge |

HA dùng registry WebSocket command và state/service REST có sẵn trong client. Tham khảo [frontend registry commands](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-strategy/), [WebSocket API](https://developers.home-assistant.io/docs/api/websocket/) và [REST API](https://developers.home-assistant.io/docs/api/rest/).

## Kiểm thử tại nhà

Sau deploy, kiểm tra với HA thật: scan/notify, ID không còn tồn tại, area kế thừa device, alias trùng, fuzzy, đọc state sau service, mount ro/rw và rollback. Bản QA đi kèm dùng mock cho HA/LLM, không chạy thiết bị thật. Đọc `QA_V1.3.0.md` để biết test đã chạy và giới hạn.
