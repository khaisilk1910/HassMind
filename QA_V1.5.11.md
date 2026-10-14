# QA — HassMind v1.5.11 Ghi chú và hình ảnh

## Kết quả tự động

- `python -m pytest -q tests/test_notes.py tests/test_chat_retention_and_auth_audit.py`: **11 passed**.
- `node --test tests/test_knowledge_ui.js`: **35 passed** (tương thích Javascript cũ, bao gồm render chat timestamp).
- `python -m compileall -q app` và `node --check static/app.js`: **passed**.

## Đã kiểm thử

- Tạo ghi chú qua Chat; sửa, ghim, bỏ ghim, nối thêm, yêu cầu xác nhận xóa; tìm kiếm với chữ Việt có dấu và không dấu, theo tag và theo mã.
- Truy hồi lại ảnh gắn với ghi chú; ảnh được giải mã/mã hóa lại; từ chối file SVG giả ảnh và file vượt giới hạn.
- Xóa ảnh, xóa ghi chú xóa file; giữ lại ghi chú sau khi bộ dọn lịch sử hội thoại chạy vào ngày sau.
- Câu `Ghi chú về ...` chỉ tìm kiếm, không tạo nhầm ghi chú. Lệnh điều khiển HA không bị xử lý nhầm thành ghi chú.
- Ảnh không liên quan câu lệnh ghi chú không được lưu.

## Chưa thể xác minh tại môi trường QA

- Import/chạy toàn bộ FastAPI/LogicFirst tích hợp thực tế, do môi trường sandbox không có `openai`/`mcp` và không cài được từ nguồn ngoài. Đã kiểm tra cú pháp nhưng các endpoint cần được kiểm tra sau khi build Docker.
- Không có Chromium headless để chụp ảnh kiểm tra UI responsive; đã kiểm tra logic JS/HTML/CSS ở mức mã nguồn và regression JS.
- Chưa kiểm tra trực tiếp trên Home Assistant, Zalo, reverse proxy, thiết bị di động hay DB sản xuất. Khuyến nghị sao lưu `/data` trước deploy và thử một ghi chú ảnh mới khi cập nhật.
