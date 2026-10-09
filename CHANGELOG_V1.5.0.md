# HassMind v1.5.0 — Logic-First Core

## Mục tiêu

HassMind 1.5.0 đổi thứ tự xử lý mặc định từ **AI-first** sang **logic-first**: code xác định trước xem yêu cầu có thể xử lý chắc chắn bằng trạng thái Home Assistant, policy, mapping và rule đã biết hay không. Chỉ phần còn mơ hồ/ngữ nghĩa/phức tạp mới chuyển sang AI.

## Thay đổi chính

### Logic-First Router

- Tất cả Web Chat, Scheduler, Event rules, Zalo và Telegram đi qua `LogicFirstOrchestrator`.
- Fast path bằng code cho truy vấn state có `entity_id` chính xác.
- Fast path cho lệnh `turn_on`/`turn_off` đơn giản trên domain được phép; state được đọc lại để xác minh trước khi báo thành công.
- Fast path mới có thể resolve **friendly_name trùng khớp chính xác** từ snapshot HA. Nếu có nhiều entity cùng tên, HassMind hỏi lại thay vì đoán.
- Request có điều kiện, ngữ nghĩa mở hoặc cần suy luận tiếp tục fallback sang Agent AI.
- API chat trả thêm `engine=logic|ai`; giao diện Chat hiển thị `⚙ logic` hoặc `🤖 AI`.

### Logic Profiles cho Scheduler/Event

- Thêm cú pháp `@logic-profile <name>` để chạy workflow deterministic, không cần model.
- Built-in profile `job3-vacancy-shutdown` cho Job 3:
  - presence cố định cho Bếp / Phòng Sóc Chíp / Phòng khách / Phòng ngủ;
  - TV map cố định và dùng như veto an toàn;
  - area mapping lấy từ HA area/entity/device registry, không fuzzy-match tên phòng;
  - chỉ xử lý `light`, `fan` và `switch` nằm trong allowlist operator xác nhận;
  - chỉ thông báo entity đã thực sự xác minh `off`.
- Prompt Job 3 cũ chứa đầy đủ 6 TV entity được tự nhận diện và route sang profile mới để giữ tương thích.
- Có thể override profile trong `/data/logic_profiles/<name>.json` mà không sửa image.

- Built-in profile `bedroom-climate-comfort` cho Scheduler tiện nghi nhiệt:
  - đọc batch presence, nhiệt độ, độ ẩm, climate và quạt từ Home Assistant;
  - top-level climate state là nguồn bật/tắt, không suy luận từ target lưu;
  - điều hòa tự động chỉ dùng `cool 27°C`, không đặt 25/26°C;
  - độ nóng được điều tiết bằng speed/preset quạt; hai phòng xử lý song song, action trong từng phòng giữ đúng thứ tự;
  - side effect được đọc fresh state để verify; script speed chỉ báo là "đã gửi lệnh" vì không có sensor tốc độ trực tiếp.
- Scheduler cũ có prompt `Dùng skill bedroom-climate-comfort...` được auto-route sang Logic Profile mới, không gọi model.

### Runtime Issue Memory

- Thêm bảng SQLite `runtime_issues` để nhớ lỗi tool/action theo operation + exact entity.
- Lỗi lặp lại trong cửa sổ cấu hình không bị retry mù liên tục.
- Với chat trực tiếp, HassMind hỏi người dùng có muốn thử lại khi cùng action đã lỗi lặp lại.
- Với automation deterministic, entity đang có repeated failure được bỏ qua để tránh spam service.
- Khi thao tác thành công trở lại, issue tương ứng được đánh dấu resolved.
- API `/api/runtime-issues` phục vụ chẩn đoán.

### Home Assistant realtime và xác minh

- Logic engine dùng một state snapshot cho truy vấn/candidate selection và đọc fresh state sau side effect để verify.
- Thêm HA WebSocket helpers cho area registry và device registry; entity registry đã có từ trước.
- Registry metadata có TTL cache, state vẫn dùng event-backed state cache của HassMind.
- Sửa normalize tiếng Việt `đ/Đ` để deterministic matching không làm mất chữ `đ` (`đèn` -> `den`).

### Concurrency

- Scheduler có thể chạy nhiều due jobs đồng thời với semaphore, mặc định `SCHEDULER_MAX_CONCURRENCY=4`.
- Nhiều Event rules khớp cùng event chạy đồng thời, mặc định `EVENT_RULE_MAX_CONCURRENCY=8`.
- Read-only tool calls của Agent AI tiếp tục được chạy song song theo cơ chế có sẵn.
- Side effect vẫn chịu policy, verification và giới hạn logic tương ứng; concurrency không bỏ qua safety boundary.

## Biến môi trường mới

```env
LOGIC_FIRST_ENABLED=true
LOGIC_PROFILES_DIR=/app/config/logic_profiles
USER_LOGIC_PROFILES_DIR=/data/logic_profiles
LOGIC_REGISTRY_CACHE_SECONDS=300
LOGIC_REPEAT_FAILURE_LIMIT=2
LOGIC_REPEAT_FAILURE_WINDOW_MINUTES=30
SCHEDULER_MAX_CONCURRENCY=4
EVENT_RULE_MAX_CONCURRENCY=8
```

## Khuyến nghị cho Job 3

Prompt tối giản và chính xác nhất sau khi nâng cấp:

```text
@logic-profile job3-vacancy-shutdown
```

Đặt `Khi nào gửi` thành **Chỉ gửi khi có thao tác thành công** (`action_only`). Prompt Job 3 dài kiểu cũ vẫn có auto-route tương thích, nhưng prompt profile ngắn giúp behavior rõ ràng và không phụ thuộc model.
