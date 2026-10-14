# HassMind v1.5.8 — Aurora Admin UI

## Giao diện admin
- Thiết kế lại giao diện tối: phân cấp rõ ràng giữa thanh điều hướng, tiêu đề trang, số liệu tổng quan, biểu mẫu và nhật ký. Dùng độ tương phản và khoảng cách dễ đọc hơn.
- Thanh điều hướng có SVG icons nhất quán và trạng thái đang chọn rõ ràng; header có nhãn trang đang mở.
- Hướng dẫn sử dụng ở đầu 13 trang mặc định được thu gọn thành "Hướng dẫn nhanh" và mở bằng click khi cần, không xóa nội dung.
- Cards có điểm nhấn màu, status badges rõ ràng, focus state cho bàn phím; nút, panel và thông báo có hiệu ứng chuyển nhẹ.
- Responsive trên điện thoại: thanh điều hướng cuộn ngang, card xếp cột, Settings tabs xếp dọc.
- Tuân thủ `prefers-reduced-motion` để hạn chế chuyển động cho người có nhu cầu trợ năng.
- Trang login được làm mới cho đồng bộ với admin.

## Settings dễ sử dụng hơn
- Ba nhóm chuyển đổi trực tiếp: **Tài khoản & API**, **Phiên & bảo mật**, **Nhật ký bảo mật**.
- Nhật ký bảo mật không còn nằm sau toàn bộ biểu mẫu cấu hình; có thể chọn ngay một tab để xem.
- Giữ phân trang 10/20/50/100 dòng đã thêm ở v1.5.7 và giữ toàn bộ form/data field cũ.

## Tương thích và bảo mật
- Phiên bản mới kế thừa việc gắn timestamp cho chat và xóa lịch sử từ ngày trước (v1.5.7).
- Không thay đổi endpoint, payload, CSRF, sessions, password policy, server-side retention hay database migrations.
- Assets CSS tách thành `static/ui-refresh.css`, load sau `app.css` để giữ tính tương thích.
- Phiên bản API, `VERSION`, admin và login đều đồng bộ thành `1.5.8`.
- Demo/screenshots dùng dữ liệu giả để kiểm thử giao diện; không phải dữ liệu Home Assistant thật.

## QA
- Python: 236 bài test đạt, 12 subtests đạt (loại trừ ba mô-đun phụ thuộc `openai` chưa cài trong môi trường kiểm thử).
- JavaScript: 35/35 test đạt.
- Browser smoke: Playwright Chromium tại 1440×900 và 390×844, Settings tabs mở đúng, aria-pressed đồng bộ, không tràn ngang.
- Python compileall và JavaScript syntax: đạt.
- Chưa test trực tiếp trên Docker/Home Assistant hoặc backend với các dịch vụ ngoài.
