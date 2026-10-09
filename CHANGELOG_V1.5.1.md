# HassMind v1.5.1 — Logic-First Recovery

## Fixed

- Sửa regression của v1.5.0 khiến Web Chat các câu ngắn như `kiểm tra phòng ngủ` / `xem trạng thái phòng ngủ` rơi thẳng sang AI và có thể nhận capability refusal thay vì đọc Home Assistant.
- Sửa `bedroom-climate-comfort` khi gọi từ Web Chat: tên skill là bằng chứng đủ mạnh để route sang Logic Profile deterministic, không chỉ Scheduler/Event source.
- Sửa Scenario Dry Run của `bedroom-climate-comfort`: trước đây `LogicFirstOrchestrator.__getattr__` làm Dry Run bypass Logic Engine và gọi LLM trực tiếp. v1.5.1 có deterministic dry-run profile, chỉ đọc state và lập planned actions, không thực thi mutation.
- Thêm room-status fast path cho các phòng đã có mapping operator-confirmed: Phòng ngủ, Phòng Sóc Chíp, Phòng khách và Bếp.
- Thêm backend AI refusal guard: capability disclaimer không còn được hiển thị như câu trả lời hợp lệ cho Home Assistant request khi model không gọi tool; lịch sử assistant được thay bằng clarification an toàn.
- Room status dùng top-level climate state, không coi `attributes.temperature` là power state.

## UX

- Scenario Dry Run hiển thị Engine `⚙ Logic` hoặc `🤖 AI`.
- `AI response preview` đổi động thành `Logic response preview` khi workflow được mô phỏng deterministic.
- Asset/version bump 1.5.1 để tránh browser cache giữ JavaScript v1.5.0.

## Compatibility

- Giữ schema database và dữ liệu v1.5.0; không cần migrate thủ công.
- Giữ Scheduler/Event notification modes và concurrency settings hiện có.
- User skill override `bedroom-climate-comfort` vẫn được giữ nguyên; code profile là lớp thực thi deterministic, không ghi đè file user skill.
