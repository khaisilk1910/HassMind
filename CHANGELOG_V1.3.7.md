# HassMind v1.3.7

## Managed Skills

- Thêm trang **Skills** trong Web Admin để tạo, sửa, validate/test, bật/tắt, xóa, xem version và rollback skill.
- Giữ `/app/config/skills` là lớp built-in read-only; skill do người dùng quản lý được lưu tại `/data/skills` trên volume dữ liệu hiện có.
- User skill cùng tên built-in hoạt động như override. Xóa override khôi phục built-in; built-in nguyên bản không thể bị xóa từ UI/API.
- Agent-facing `skill_list`/`skill_read` chỉ nhìn thấy skill hợp lệ và đang enabled. Admin vẫn thấy skill invalid/disabled để sửa.

## Validation, history và an toàn ghi file

- Validate slug tên skill, YAML frontmatter `name`/`description`, kích thước tối đa 128 KiB, NUL byte và body rỗng; cảnh báo description/body quá ngắn hoặc thiếu heading.
- Mỗi thay đổi tạo snapshot version trong `/data/skills/.history`; metadata enabled/version nằm trong `/data/skills/.meta`.
- Rollback tạo một version mới thay vì ghi đè lịch sử cũ.
- Ghi file theo kiểu atomic replace; thư mục user skill cố gắng giữ mode `0700`, file `0600`.
- Chặn path traversal bằng tên skill dạng slug và từ chối file `.md` là symbolic link để không đọc nội dung ngoài storage được quản lý.
- API mutation chỉ dành cho Admin, dùng cơ chế session/CSRF hiện có và ghi admin audit + structured log.

## Skills Home Assistant cài sẵn

Bổ sung/chuẩn hóa 21 skill built-in:

`smart-home-router`, `presence-aware-control`, `lighting-optimizer`, `climate-comfort`, `device-health-monitor`, `automation-review`, `automation-designer`, `knowledge-curator`, `notification-intelligence`, `home-security-monitor`, `energy-optimization`, `battery-maintenance`, `night-mode`, `arrival-departure`, `air-quality-manager`, `water-leak-response`, `integration-orchestration`, `daily-home-report`, `self-maintenance`, `incident-diagnosis`, `troubleshoot-device`.

Tất cả có frontmatter thống nhất và workflow/safety rule hướng đến Home Assistant realtime, idempotent control, proposal/approval cho thay đổi cấu hình và tránh suy đoán từ dữ liệu tĩnh.

## Agent và deployment

- System prompt hướng agent dùng `skill_list` rồi `skill_read` khi yêu cầu khớp workflow lặp lại.
- Thêm `USER_SKILLS_DIR=/data/skills` vào settings, env examples và các file Docker Compose/Stack/Portainer.
- `setup.sh` và image tạo sẵn `/data/skills`; không cần đổi mount `/app/config` sang read-write.
- Bump phiên bản ứng dụng/UI lên `1.3.7`.
