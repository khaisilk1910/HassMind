# HƯỚNG DẪN — HassMind v1.5.18: Sửa logic tìm kiếm ghi chú

## Thành phần cần cập nhật

Chỉ cần thay mã nguồn/build lại **HassMind**. Zalo Bot Server v1.5.17 và HACS vẫn dùng bản cũ. Không có migration database.

## Triển khai

1. Sao lưu volume dữ liệu `/data` (đặc biệt SQLite và thư mục `note_images`).
2. Giải nén `HassMind-v1.5.18-fix-note-search.zip` vào thư mục mã nguồn HassMind hiện tại (hoặc build tại đường dẫn mới nhưng đảm bảo volume dữ liệu **trỏ về cùng thư mục cũ**).
3. Kiểm tra Docker Compose đang sử dụng `build:` từ mã nguồn vừa cập nhật, không dùng image GHCR chưa có bản vá.
4. Tại thư mục có tệp `docker-compose.yml` chạy:

   ```bash
   docker compose up -d --build --force-recreate
   ```

5. Làm mới trang HassMind (Ctrl + F5), xác nhận phiên bản 1.5.18 trong giao diện/trang health.

## Lệnh kiểm thử từ Web hoặc Zalo

- `Tìm ghi chú thuốc an thần`: chỉ ghi chú thuốc an thần (và ảnh của ghi chú đó).
- `Tìm ghi chú thuốc giảm đau`: chỉ ghi chú thuốc giảm đau.
- `Tìm ghi chú nhà thờ tổ`: chỉ ghi chú nhà thờ tổ.
- `Tìm ghi chú thuốc`: tất cả ghi chú về thuốc, không trả ghi chú nhà thờ tổ.
- `Danh sách ghi chú`: xem tất cả ghi chú.
- `Tìm ghi chú thuốc không tồn tại`: thông báo không tìm thấy.
- `tim ghi chu thuoc an than`: cũng được nhận diện (không dấu).

## Lưu ý

- Cơ chế so khớp được chỉnh theo hướng thận trọng để tránh trả ghi chú/ảnh sai. Khi sai chính tả hoặc các từ khóa cần thiết không xuất hiện, HassMind sẽ báo không tìm thấy thay vì trả các ghi chú chỉ trùng 1 từ.
- Album ảnh, luồng tạo ghi chú chờ 60 giây, dữ liệu ghi chú cũ đều được giữ nguyên.
- Phiên bản này được thử bằng kiểm thử tự động; cần xác nhận thêm trên hệ thống thật sau khi nâng cấp.
