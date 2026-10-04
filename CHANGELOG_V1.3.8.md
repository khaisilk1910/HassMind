# HassMind v1.3.8

## Skills UI layout hotfix

- Sửa lỗi trang **Skills** bị co thành các cột rất hẹp trên màn hình desktop do thiếu CSS cho `span-7` và `span-5`.
- Bổ sung đầy đủ grid span 5/7 để hai khối **Installed skills** và **Tạo/Sửa skill** chiếm đúng tỷ lệ 7/12 và 5/12.
- Thêm `min-width: 0` cho card trong Skills để nội dung, nút và textarea không làm vỡ grid.
- Giới hạn hợp lý chiều rộng ô tìm kiếm và đảm bảo danh sách skill luôn chiếm 100% card.
- Nâng breakpoint riêng của trang Skills lên `1280px`: màn hình vừa/nhỏ sẽ tự xếp hai card thành một cột, tránh giao diện chật khi sidebar vẫn hiển thị.
- Tăng version asset query lên `1.3.8` để trình duyệt không dùng lại CSS/JS v1.3.7 bị cache.

Không thay đổi API quản lý skill, dữ liệu `/data/skills`, version history hoặc cơ chế rollback.
