# HassMind v1.4.0 — Bedroom Climate Comfort

## Added
- Built-in skill `bedroom-climate-comfort` cho Phòng ngủ và Phòng Sóc Chíp.
- Mapping entity cố định theo cấu hình đã xác nhận, gồm sensor nhiệt độ/độ ẩm, presence, climate và hai kiểu quạt trần.
- Comfort heuristic có humidity bias, decision bands, giới hạn setpoint 25–27°C, hysteresis 15 phút và chống lặp fan speed.
- Prompt mẫu thứ 22 trên trang Chat và hỗ trợ Scenario Dry Run cho skill mới.
- Cấu hình `ALLOW_SCRIPT_ENTITIES` để cho phép chính xác 6 script tốc độ quạt Phòng ngủ mà không mở toàn bộ domain `script`.

## Safety
- Chỉ tự điều khiển phòng có presence=`on`; sensor/presence `unknown` hoặc `unavailable` thì không action.
- Không dùng `heat`, không đặt nhiệt độ tự động dưới 25°C, không tuyên bố logic tiện nghi có thể phòng bệnh.
- `script.turn_on` chỉ hợp lệ khi target là exact entity trong allowlist, không cho target theo area/device và không cho variables/data.
- Scenario Dry Run vẫn suppress toàn bộ action và chỉ hiển thị planned action/policy.

## Fixed
- Chuẩn hóa entity độ ẩm Phòng Sóc Chíp thành `sensor.xiaomi_m15_1480_relative_humidity` (loại bỏ dấu `.` thừa ở đầu input ban đầu).
