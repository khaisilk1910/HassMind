# HassMind v1.5.11 — Ghi chú lâu dài với hình ảnh & truy hồi qua Chat

## Chức năng mới

- **Ghi chú bằng câu lệnh tự nhiên:** `Ghi chú: nội dung`, `Tìm ghi chú về ...`, `Liệt kê ghi chú`, `Xem ghi chú #MÃ`, hỗ trợ tiếng Việt có/không dấu khi tra cứu.
- **Trả lại nội dung gốc + ảnh** khi hỏi trực tiếp về ghi chú, hoặc với câu hỏi tự nhiên đủ dấu hiệu liên quan. Kết quả không được AI tự viết lại nên tránh tự bịa dữ kiện trong ghi chú.
- **Chat multimodal:** tải tối đa 5 ảnh JPEG/PNG/WebP/GIF trong cùng tin nhắn ghi chú. Có thể chọn file, dán ảnh hoặc kéo thả. Nhấn vào ảnh của câu trả lời để xem ảnh lớn. Khi tải lại lịch sử trong ngày, ảnh của ghi chú vẫn xuất hiện trong phản hồi.
- **Bổ sung ảnh cho ghi chú cũ qua Chat:** `Thêm ảnh vào ghi chú #MÃ: mô tả thêm` rồi gửi kèm ảnh.
- **Quản lý ghi chú bằng Chat:** `Sửa ghi chú #MÃ: ...`, `Thêm vào ghi chú #MÃ: ...`, `Ghim ghi chú #MÃ`, `Bỏ ghim ghi chú #MÃ`; xóa chỉ sau câu lệnh `Xóa ghi chú #MÃ xác nhận`.
- **Mục Ghi chú trong Web Admin:** tìm kiếm tức thì, xem thẻ ảnh, tạo/sửa/xóa/ghim, thêm/xóa ảnh, chỉnh nhãn; hiển thị kết quả ảnh đầy đủ.
- **Truy hồi có chỉ mục:** SQLite FTS5 (nếu khả dụng), fallback SQLite LIKE; chuẩn hóa chữ hoa/thường và dấu tiếng Việt; đồng nhất “máy lạnh”/“điều hòa” khi tìm kiếm. Tìm đúng ghi chú qua mã là tuyệt đối.

## Lưu trữ và quyền riêng tư

- `notes`, `note_images`, `notes_fts` trong DB tại `DB_PATH`, mặc định `/data/hassmind.db`; ảnh dưới `/data/note_images` với tên sinh ngẫu nhiên.
- Ghi chú và ảnh **không bị xóa** theo chính sách lịch sử chat một ngày. Lưu ý backup **toàn bộ volume `/data`**.
- File ảnh được kiểm định bằng trình giải mã Pillow, giới hạn dung lượng/kích thước, mã hóa lại, bỏ metadata, kiểm soát truy cập qua endpoint bắt buộc xác thực; không mount công khai thư mục ảnh.
- Các endpoint chỉnh sửa/xóa yêu cầu API token hoặc session admin và CSRF tương ứng, cùng chính sách Host/Origin/IP đang có.
- Nội dung ghi chú được coi là dữ liệu không tin cậy, không tự biến thành câu lệnh điều khiển thiết bị Home Assistant. Câu hỏi về **state hiện tại** tiếp tục dùng cơ chế truy vấn live của HassMind.

## API

- `POST /api/chat` (JSON) bổ sung `engine: notes`, `notes[]` khi dùng lệnh ghi chú, vẫn tương thích caller cũ.
- `POST /api/chat/notes` (multipart: `message`, `session_id`, `files[]`).
- `GET /api/notes?q=&limit=&offset=`, `POST /api/notes`, `GET|PUT|DELETE /api/notes/{id}`.
- `POST /api/notes/{id}/images`, `DELETE /api/notes/{id}/images/{image_id}`, `GET /api/notes/images/{image_id}`.
- `GET /api/messages/{session_id}` có thêm `notes[]` cho phản hồi ghi chú trong ngày, không thay đổi cấu trúc thông thường.

## Nâng cấp

- Tự tạo bảng ghi chú khi khởi động, tự bổ sung `messages.note_ids_json` vào DB cũ.
- Thêm phụ thuộc `Pillow>=11,<13`. Deploy lại image Docker bằng bản mã nguồn mới; giữ nguyên volume `/data` để không mất dữ liệu.
- Giới hạn: tối đa 5 ảnh/ghi chú, 5 MB/ảnh, 16 MB/tổng HTTP multipart; nội dung ghi chú tối đa 12.000 ký tự. Ảnh được lưu để hiển thị, không có tính năng OCR/nhận dạng chữ trong ảnh trong phiên bản này. Muốn tìm theo ảnh, hãy mô tả trong phần nội dung ghi chú.
- Không thay đổi cơ chế bảo mật/settings v1.5.10.
