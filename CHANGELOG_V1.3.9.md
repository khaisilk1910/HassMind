# HassMind v1.3.9

## Skill Scenario Dry Run

- Thêm API admin `POST /api/skills/{name}/dry-run` để chạy một skill với prompt tình huống mà không thực thi mutation/action.
- Skill được chọn bị cố định trong phiên mô phỏng; `skill_list` và `skill_read` không được đưa cho model trong lượt Dry Run để tránh tự chuyển sang skill khác.
- Tool chỉ-đọc được phép truy vấn dữ liệu thực tế để preview sát trạng thái Home Assistant/Knowledge hiện tại.
- Mọi tool có khả năng gây side effect được intercept trước `ToolRuntime.call`, ghi lại thành `planned_action` và trả kết quả mô phỏng cho model. `actions_executed` luôn bằng `0` trong response của Scenario Dry Run.
- Policy của action vẫn được kiểm tra để phân loại `allowed`, `conditional` hoặc `blocked`, nhưng kết quả policy không làm action được thực thi trong Dry Run.
- Siết boundary cho Custom HTTP Integration: chỉ action khai báo `mode=read` và dùng `GET` mới có thể chạy trong Dry Run. Action gắn nhãn read nhưng dùng `POST/PUT/PATCH/DELETE` vẫn bị suppress và báo `conditional`.
- Dry Run ghi admin audit và structured log gồm skill, số planned actions, số read tools, policy và duration.

## Skills UI

- Thêm card **Test bằng tình huống** trên trang Skills.
- Có selector skill, ô Test prompt, nút **Dùng câu mẫu** và **Dry Run Skill**.
- Mỗi skill hợp lệ có nút **Dry-run** để mở nhanh đúng skill.
- Kết quả hiển thị: skill/version/source, policy, xác nhận `NO — Dry Run`, số read tool đã chạy, tool dự kiến/đã dùng, action dự kiến + arguments đã redact, reason policy, số vòng và AI response preview.
- Giữ nguyên nút **Test** cũ cho validation cấu trúc; Test và Scenario Dry Run là hai chức năng độc lập.

## Chat prompt library

- Thêm khối thu gọn **Câu hỏi mẫu cho Skills** trên trang Chat; mặc định đóng để không chiếm không gian.
- Có tìm kiếm theo tên skill hoặc nội dung prompt.
- Có nút **Chèn câu hỏi** để đưa mẫu vào ô chat, người dùng vẫn có thể sửa trước khi gửi.
- Cài đủ 21 câu mẫu cho toàn bộ built-in Home Assistant skills:
  `smart-home-router`, `presence-aware-control`, `lighting-optimizer`, `climate-comfort`, `device-health-monitor`, `troubleshoot-device`, `automation-review`, `automation-designer`, `knowledge-curator`, `notification-intelligence`, `home-security-monitor`, `energy-optimization`, `battery-maintenance`, `night-mode`, `arrival-departure`, `air-quality-manager`, `water-leak-response`, `integration-orchestration`, `daily-home-report`, `self-maintenance`, `incident-diagnosis`.

## Compatibility

- Không thay đổi schema dữ liệu `/data/skills`, version history hoặc rollback của v1.3.7/v1.3.8.
- Không cần database migration.
- Asset cache key được tăng lên `1.3.9`.
