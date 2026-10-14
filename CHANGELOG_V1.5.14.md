# HassMind v1.5.14 – Zalo ghi chú nội dung trước, chờ ảnh 60 giây

## Luồng mới riêng cho Zalo

1. Gửi `Ghi chú: Nội dung ...` **trước khi gửi ảnh**. HassMind xác nhận đã tiếp nhận nội dung, hỏi có muốn đính kèm ảnh không.
2. Chờ **60 giây** kể từ lúc nhận nội dung; có thể gửi lần lượt tới 5 ảnh. Sau mỗi ảnh hệ thống xác nhận số ảnh đã lưu.
3. Gửi `Xong`, `Không có ảnh`, hoặc `Lưu ngay` để kết thúc sớm. Nếu người dùng im lặng, tác vụ nền tự hoàn tất sau 60 giây, lưu cả trường hợp chỉ có chữ.
4. Nếu ảnh lỗi tải, nội dung bản nháp **không bị hủy**, tiếp tục chờ ảnh thay thế đến hết hạn, rồi lưu ghi chú chữ nếu không nhận được ảnh.
5. Người dùng gửi ảnh *trước khi có ghi chú* sẽ được nhắc tạo nội dung trước, không tích lũy ảnh không rõ mục đích.
6. Các bản nháp được lưu ở SQLite (`zalo_note_drafts`, cùng cơ sở dữ liệu `/data/hassmind.db`) nên tiếp tục được tự hoàn tất sau khi dịch vụ khởi động lại. Ghi chú và ảnh đã hoàn thành ở `notes`/`note_images` như trước.
7. Nếu bắt đầu nội dung ghi chú mới khi còn bản nháp cũ, bản cũ được hoàn tất trước để tránh mất dữ liệu.

## Nhận ảnh Zalo ổn định hơn

- Ưu tiên ảnh đã lưu tạm bởi Zalo Server và lấy qua API xác thực; thử URL CDN trong webhook nếu relay không có ảnh.
- Thông báo chính xác hơn khi server đưa mã lỗi HTTP 401/403/404, lỗi mạng, file quá lớn, định dạng không hợp lệ hoặc thiếu URL.
- Zalo Server v1.2.8 Photo Bridge kèm theo đã bổ sung **sử dụng proxy gắn với tài khoản Zalo** khi tải ảnh, gửi `Referer`/`User-Agent`, và thử bản ảnh thumbnail nếu ảnh chính bị CDN từ chối.
- Zalo Server gửi thông tin trạng thái `_hassmindPhoto` và mã lỗi an toàn `_hassmindPhotoError` ngay cả khi không tải được ảnh. Không đẩy URL/ảnh bí mật vào logs.
- **Không sửa Zalo HACS**; chức năng gửi ngược ảnh ghi chú qua Zalo `/api/sendImageByAccount` giữ nguyên.

## Giới hạn kiểm chứng

Đã kiểm thử bằng unit/mocked handlers và kiểm tra cú pháp. Chưa kiểm thử với tài khoản Zalo đang hoạt động. Nếu CDN trả 403/401 bất kể URL và proxy, vẫn cần log thực tế hoặc cách tải media đã xác thực tương thích với SDK. Việc thêm `Referer` và proxy cải thiện đường lấy ảnh nhưng không bảo đảm vượt qua hạn chế truy cập của Zalo CDN.
