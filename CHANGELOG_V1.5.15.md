# HassMind v1.5.15 — một tin ảnh Zalo cho mỗi ghi chú

## Thay đổi

- Ghi chú có 2–5 ảnh: tạo một ảnh tổng hợp (lưới) khi trả lời Zalo; ảnh **gốc** vẫn được lưu riêng trong SQLite + `/data/note_images` và xem từng ảnh trên Web.
- Gửi ảnh tổng hợp bằng đúng API `POST /api/sendImageByAccount` đã có ở Zalo Server, truyền `message` bằng **nội dung ghi chú** (không còn dùng chuỗi `📷 <tiêu đề>`).
- Ghi chú có 1 ảnh: cũng dùng nội dung ghi chú làm caption.
- Khi người dùng hỏi/tìm/xem ghi chú bằng Zalo, không gửi một tin chữ trùng lặp trước tin ảnh. Mỗi ghi chú có ảnh trả đúng một tin ảnh có caption. Ghi chú chỉ có chữ vẫn được trả bằng tin chữ.
- Album JPEG được dựng **theo yêu cầu**, không lưu thêm bản sao trên đĩa. Endpoint `/media/zalo-note-albums/{id}` có HMAC riêng cho album, thời hạn ngắn, trả `Cache-Control: private, no-store`.
- Giữ nguyên luồng tạo ghi chú: nội dung trước, chờ ảnh 60 giây, vẫn tự lưu nếu không có ảnh.

## Lý do chọn ảnh tổng hợp thay vì album đính kèm gốc

Thư viện `zca-js` chấp nhận nhiều ảnh trong một lời gọi `sendMessage`, nhưng khi có `msg` và từ hai ảnh trở lên, SDK gửi **tin chữ riêng** rồi mới gửi ảnh. Điều này không đáp ứng đồng thời yêu cầu *một tin ảnh duy nhất* và *caption là nội dung ghi chú*. Bản này tạo một JPEG chứa đủ ảnh để dùng cơ chế caption **một ảnh** vốn đã hoạt động trên Zalo Server hiện tại.

## Giới hạn

- Bản hiển thị tổng hợp có thể được Zalo nén; ảnh gốc luôn còn riêng trong HassMind.
- Để tránh giới hạn chú thích của Zalo, caption dài hơn 1.800 ký tự được rút gọn kèm thông báo xem toàn bộ trên HassMind.
- Nếu một ghi chú có ảnh bị xóa/mất khỏi lưu trữ, hệ thống không gửi album thiếu ảnh; thay vào đó thông báo lỗi.
- Chưa xác nhận hiển thị thực tế trên tài khoản Zalo của người dùng; đã kiểm thử mã nguồn và đường vận chuyển giả lập.

## Triển khai

1. Sao lưu volume `/data` HassMind.
2. Cập nhật và build lại **HassMind**: `docker compose up -d --build --force-recreate`.
3. **Không cần đổi Zalo Server v1.5.14 hay Zalo HACS** (API gửi một ảnh đã có sẵn).
4. Bảo đảm `ZALO_MEDIA_BASE_URL` trỏ tới địa chỉ HassMind mà container Zalo Server truy cập được.
5. Trên Zalo, gửi `Tìm ghi chú nhà thờ tổ`. Nếu ghi chú có nhiều ảnh, bạn sẽ nhận một ảnh lưới cùng caption, không phải nhiều tin ảnh rời.
