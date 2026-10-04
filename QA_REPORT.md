# HassMind v1.2.4 — QA report

## Kiểm tra backend

PASS:

- `python -m compileall -q app`
- SQLite migration tạo `custom_integrations` mà không thay đổi/xóa `integration_settings` hiện có.
- CRUD Custom Integration: create → list → update → delete.
- ID validation, URL validation, health-path validation và HTTP-header validation.
- Secret lưu ngoài SQLite trong `/data/secrets/integration_custom_<id>_secret`.
- API/public view không trả secret thật; chỉ trả `secret_configured`.
- Đổi auth về `none` hoặc chọn xóa credential sẽ xóa runtime secret.
- IntegrationHub nạp Custom Integration và reconfigure runtime.
- Health check thực tế với local HTTP test server + Bearer auth: PASS.
- Health status response không chứa credential.
- Disable Custom Integration sau reconfigure trả `status=disabled`.

## Kiểm tra frontend

PASS:

- `node --check static/app.js`
- Các built-in Integration dùng `<details>` không có thuộc tính `open`, vì vậy mặc định thu gọn.
- Custom Integration dùng cùng cơ chế thu gọn mặc định.
- Nút **Thêm Integration** mở form tạo mới.
- Create/update/delete dùng API riêng và reload danh sách sau thành công.
- Layout responsive có breakpoint 3/2/1 cột.
- Credential input luôn là `type=password`, giá trị secret cũ không được render lại.

## Kiểm tra package

PASS trước khi đóng gói:

- Không chứa `.env` runtime, SQLite database, log runtime hay credential thật.
- Xóa `__pycache__`/`.pyc` khỏi package.
- Version đồng bộ `1.2.4` ở backend, frontend, `VERSION` và HTML cache-busting.

## Ghi chú

Custom HTTP Integration ở v1.2.4 là registry + health monitoring. Tool/action cho AI không được tạo tự động; đây là chủ ý bảo mật để tránh generic HTTP tunnel do LLM điều khiển.
- Headless Chromium render bằng mock data: card Integrations đóng mặc định, mở đúng khi click, card đang mở tự span rộng hơn để form không bị bó hẹp, form Thêm Integration hiển thị đúng.
