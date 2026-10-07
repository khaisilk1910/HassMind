# HassMind 1.2.1 - password change fix

## Lỗi đã sửa

Khi mật khẩu mới không đạt policy (ví dụ ngắn hơn `PASSWORD_MIN_LENGTH`, chứa username, hoặc dưới 20 ký tự nhưng không đủ 3 nhóm ký tự), `validate_password()` phát sinh `ValueError`. Trước bản 1.2.1 lỗi này đi tới global exception handler nên UI chỉ nhận HTTP 500 `Internal server error`.

## Thay đổi

- Chuyển lỗi policy mật khẩu ở đổi/reset mật khẩu thành HTTP 400 với thông báo cụ thể.
- Ghi auth audit `password_policy_rejected` nhưng không ghi nội dung mật khẩu.
- Validation username không hợp lệ cũng trả HTTP 400 thay vì HTTP 500.
- UI hiển thị chính xác `PASSWORD_MIN_LENGTH` và quy tắc password.
- UI chặn sớm mật khẩu ngắn hơn policy trước khi gọi API.
- Tăng version lên 1.2.1.

## Policy mặc định

- Tối thiểu 14 ký tự (`PASSWORD_MIN_LENGTH=14`).
- Không chứa username.
- Nếu mật khẩu ngắn hơn 20 ký tự, phải có ít nhất 3 nhóm: chữ thường, chữ hoa, số, ký tự đặc biệt.
