---
name: bedroom-climate-comfort
description: Tự điều phối nhiệt độ và độ ẩm cho Phòng ngủ và Phòng Sóc Chíp bằng cảm biến Xiaomi, điều hòa và quạt trần; dùng khi người dùng muốn kiểm tra hoặc tự điều chỉnh tiện nghi nhiệt ở hai phòng này theo hiện diện thực tế.
---

# Objective
Giữ hai phòng dễ chịu, tránh quá nóng hoặc quá lạnh bằng thay đổi tối thiểu và có kiểm soát. Đây là logic tiện nghi nhiệt, không phải tư vấn y khoa và không được tuyên bố có thể phòng bệnh.

# Fixed room map
Dùng đúng các entity_id dưới đây; đây là mapping đã được người vận hành xác nhận, không cần fuzzy resolve.

## Phòng ngủ
- Temperature: `sensor.xiaomi_m9_daa3_temperature`
- Humidity: `sensor.xiaomi_m9_daa3_relative_humidity`
- Climate: `climate.xiaomi_m9_daa3_air_conditioner`
- Ceiling fan power: `switch.ct3_ngoai_pn_kn_left`
- Fan speed 1: `script.fan_light_pn_kn_fan_1`
- Fan speed 2: `script.fan_light_pn_kn_fan_2`
- Fan speed 3: `script.fan_light_pn_kn_fan_3`
- Fan speed 4: `script.fan_light_pn_kn_fan_4`
- Fan speed 5: `script.fan_light_pn_kn_fan_5`
- Fan speed 6: `script.fan_light_pn_kn_fan_6`
- Presence: `binary_sensor.pn_status`

## Phòng Sóc Chíp
- Temperature: `sensor.xiaomi_m15_1480_temperature`
- Humidity: `sensor.xiaomi_m15_1480_relative_humidity`
- Climate: `climate.xiaomi_m15_1480_air_conditioner`
- Ceiling fan power: `switch.ct4_phong_soc_chip_l3`
- Ceiling fan entity: `fan.sonoff_1000a827dd`
- Supported preset modes expected: `off`, `low`, `medium`, `high`
- Presence: `binary_sensor.ph_status`

# Read workflow
1. Dùng một lần `ha_get_states` với toàn bộ entity cần thiết và `include_attributes=true`. Với Phòng ngủ, đọc thêm 6 script tốc độ để xem `last_triggered` nếu có.
2. Không lấy nhiệt độ/độ ẩm hiện tại từ Knowledge. Sensor Home Assistant là nguồn realtime.
3. Với mỗi phòng, xác nhận temperature và humidity là số hợp lệ; climate/presence không ở `unknown`/`unavailable`.
4. Chỉ tự điều khiển phòng có presence=`on`. Nếu presence=`off`, không bật mới hoặc tăng mức làm mát trong skill này. Nếu presence không xác định, không action.
5. Nếu sensor môi trường lỗi, non-numeric hoặc rõ ràng quá cũ/bất thường, không tự tăng cooling; báo cần kiểm tra sensor.

# Climate state interpretation
- Luôn dùng top-level `state` của climate entity để xác định điều hòa bật/tắt.
- `state=off` nghĩa là điều hòa đang tắt, kể cả khi `attributes.temperature` vẫn giữ target cũ.
- `attributes.temperature` chỉ là target lưu, không phải power state.
- `state=cool` nghĩa là điều hòa đang ở mode cool; `hvac_action=idle` chỉ nghĩa compressor hiện nghỉ, không có nghĩa điều hòa đã tắt.
- Nếu phòng có người, `effective_temp >= 27.5`, climate đang `off` và `cool` được hỗ trợ: bật `cool` và đặt 27°C.
- Không được kết luận `không cần action` trong trường hợp trên.

# Comfort heuristic
Dùng nhiệt độ phòng làm tín hiệu chính và độ ẩm chỉ để hiệu chỉnh nhẹ. Không gọi đây là chỉ số y khoa.

Tính `effective_temp` theo heuristic:
- humidity >= 80%: `T + 1.0`
- 70-79%: `T + 0.6`
- 65-69%: `T + 0.3`
- 40-64%: `T`
- < 40%: `T - 0.2`

Nếu humidity < 35%, tránh làm lạnh mạnh. Điều hòa tự động vẫn giữ target cố định 27°C; không hạ thấp hơn để bù độ ẩm.

# Decision bands
Áp dụng riêng cho từng phòng đang có người:

1. **Quá lạnh** — `T <= 23.0` hoặc `effective_temp <= 23.5`
   - Không bật điều hòa.
   - Nếu climate đang ở `cool` hoặc `dry`, ưu tiên `climate.turn_off` để ngừng làm lạnh.
   - Tắt quạt trần.

2. **Dễ chịu/mát** — `effective_temp < 26.0`
   - Nếu điều hòa đang tắt: giữ tắt.
   - Nếu điều hòa đang bật để làm lạnh: không hạ setpoint; nếu target < 27°C thì đưa về 27°C.
   - Quạt tắt khi `effective_temp < 25.0`; từ 25.0 đến <26.0 có thể dùng mức thấp nếu người trong phòng vẫn cần gió.

3. **Hơi ấm** — `26.0 <= effective_temp < 27.5`
   - Nếu điều hòa đang tắt: chưa bắt buộc bật; ưu tiên quạt thấp/vừa.
   - Nếu điều hòa đang bật: dùng `cool`, target 27°C.
   - Phòng ngủ: fan speed 2.
   - Phòng Sóc Chíp: preset `low`.

4. **Ấm** — `27.5 <= effective_temp < 29.0`
   - Bật/giữ điều hòa `cool`, target 27°C.
   - Phòng ngủ: fan speed 3.
   - Phòng Sóc Chíp: preset `medium`.

5. **Nóng** — `29.0 <= effective_temp < 30.5`
   - Bật/giữ điều hòa `cool`, target 27°C. Không hạ target; tăng mức quạt để tăng cảm giác mát.
   - Phòng ngủ: fan speed 4; nếu `T >= 30.0` dùng speed 5.
   - Phòng Sóc Chíp: preset `high`.

6. **Rất nóng** — `effective_temp >= 30.5`
   - Bật/giữ điều hòa `cool`, target 27°C. Không hạ target; dùng mức quạt cao nhất phù hợp.
   - Phòng ngủ: fan speed 6.
   - Phòng Sóc Chíp: preset `high`.

# High humidity handling
- Khi humidity >=75%, `24.5 <= T < 27.5`, climate hỗ trợ `dry`, và climate vừa không đổi mode trong khoảng 15 phút: có thể ưu tiên `dry` thay vì `cool`; không dùng độ ẩm cao làm lý do hạ target dưới 27°C.
- Không dùng `dry` khi phòng đã lạnh (`T < 24.5`) hoặc đang nóng rõ (`T >= 27.5`); khi nóng dùng `cool` theo bảng trên.
- Nếu mode `dry` không hỗ trợ setpoint đáng tin cậy, chỉ đổi mode và không ép temperature.
- Không liên tục đảo `dry` <-> `cool` quanh ngưỡng; giữ mode hiện tại nếu chênh lệch nhỏ.

# Hysteresis and anti-chatter
1. Không gọi action nếu thiết bị đã ở đúng mode/target/preset mong muốn.
2. Chỉ đổi target điều hòa khi chênh ít nhất 1°C.
3. Nếu climate `last_changed` dưới 15 phút, tránh đổi mode hoặc target lần nữa, trừ khi `T >= 30.5` hoặc `T <= 22.5`.
4. Target cooling tự động duy nhất là 27°C. Không tự đặt 25°C hoặc 26°C; khi phòng nóng hơn, tăng quạt thay vì hạ setpoint.
5. Không dùng `heat` hoặc auto-heat.
6. Với Phòng ngủ, nếu speed mong muốn trùng script có `last_triggered` gần nhất trong vòng 20 phút và nguồn quạt vẫn `on`, không trigger lại script đó.
7. Với Phòng Sóc Chíp, chỉ gọi `fan.set_preset_mode` khi `preset_mode` hiện tại khác mức mong muốn.

# Actuation details
## Điều hòa
- Bật/chọn mode: `ha_call_service` domain `climate`, service `set_hvac_mode`, target climate entity, data `{"hvac_mode":"cool"}` hoặc `dry` khi đủ điều kiện.
- Đặt nhiệt độ: domain `climate`, service `set_temperature`, target climate entity, data `{"temperature":27}`. Không tự đặt target dưới 27°C.
- Tắt khi quá lạnh: domain `climate`, service `turn_off`.
- Chỉ dùng mode xuất hiện trong attribute `hvac_modes`; nếu thiếu mode mong muốn thì không đoán.

## Quạt trần Phòng ngủ
- Tắt: `switch.turn_off` target `switch.ct3_ngoai_pn_kn_left`.
- Bật: trước tiên `switch.turn_on` target `switch.ct3_ngoai_pn_kn_left` nếu đang off.
- Chọn tốc độ: gọi `script.turn_on` với target là đúng một trong 6 script tốc độ đã liệt kê, data rỗng.
- Chỉ các script fan speed này được phép; không gọi script khác.

## Quạt trần Phòng Sóc Chíp
- Tắt: nếu cần, đặt preset `off`, sau đó `switch.turn_off` target `switch.ct4_phong_soc_chip_l3`.
- Bật: `switch.turn_on` target nguồn nếu đang off, rồi `fan.set_preset_mode` target `fan.sonoff_1000a827dd` với `low`, `medium` hoặc `high`.
- Không dùng preset ngoài danh sách thực tế từ attributes.

# Ordering and verification
1. Khi cần tăng làm mát: bật nguồn quạt -> đặt tốc độ quạt; đặt HVAC mode -> đặt temperature nếu mode hỗ trợ.
2. Khi phòng quá lạnh: giảm/tắt nguồn làm lạnh và quạt; không tăng bất kỳ action làm mát nào.
3. Sau khi có action thật, đọc lại các entity bị thay đổi bằng `ha_get_states` để xác nhận. Nếu Home Assistant chưa phản ánh thay đổi ngay, báo `đã gửi lệnh, đang chờ state cập nhật` thay vì khẳng định sai.
4. Dry Run chỉ lập kế hoạch action; không được coi planned action là đã thực thi.

# Continuous operation
Với Scheduler/Event tự động, ưu tiên **Logic Profile deterministic** để không cần AI:

`@logic-profile bedroom-climate-comfort`

Prompt cũ có chứa tên skill vẫn được HassMind v1.5.0 auto-route sang Logic Profile khi chạy từ Scheduler/Event. Skill chỉ cần Agent AI khi được dùng trong chat/ngữ cảnh chưa đi qua profile logic.

Skill chỉ chạy khi Agent được gọi. Nếu người dùng yêu cầu tự động theo lịch và chưa có Scheduler phù hợp, ưu tiên tạo **một** Scheduler disabled bằng `schedule_propose` thay vì tạo nhiều job cho từng mốc giờ.

- Nếu người dùng muốn chạy trong một khung giờ (đặc biệt ban đêm), ví dụ mỗi 30 phút từ 23:00 đến trước 06:00 mỗi ngày:
  - schedule_type: `window`
  - schedule_value: `{"start":"23:00","end":"06:00","every_minutes":30,"weekdays":[0,1,2,3,4,5,6]}`
  - Với khung qua đêm, `weekdays` là ngày **bắt đầu** khung giờ.
- Nếu chỉ chạy vào một số thứ ở một giờ cố định, dùng `schedule_type: weekly`, ví dụ `{"time":"21:00","weekdays":[0,2,4]}`.
- Chỉ dùng `schedule_type: interval` (ví dụ `600` giây) khi người dùng thực sự muốn chạy liên tục 24/7 không phụ thuộc giờ/ngày.
- Có thể dùng `daily` cho một giờ cố định mỗi ngày hoặc `once` cho một lần duy nhất.

Thiết lập notification khuyến nghị:
- notify: true
- notify_mode: `actionable`
- prompt: `Dùng skill bedroom-climate-comfort kiểm tra Phòng ngủ và Phòng Sóc Chíp. Chỉ điều khiển phòng đang có người, tuân thủ hysteresis, chỉ gửi thông báo nếu có action thực sự hoặc có lỗi sensor/thiết bị cần chú ý.`

Người dùng phải tự bật Scheduler trên dashboard sau khi kiểm tra lịch/prompt và Dry Run.

# Response format
Trả lời ngắn theo từng phòng:
- Presence, nhiệt độ, độ ẩm, mức đánh giá.
- Climate hiện tại -> action đã thực hiện hoặc `không cần thay đổi`.
- Fan hiện tại -> action đã thực hiện hoặc `không cần thay đổi`.
- Nếu không action, nói rõ lý do.
- Không nói rằng logic này có thể ngăn cảm cúm/ốm; chỉ mô tả mục tiêu là tránh nóng/lạnh quá mức và giữ tiện nghi.
