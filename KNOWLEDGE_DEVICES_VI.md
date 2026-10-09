# Knowledge → Devices – Hướng dẫn sử dụng (v1.5.2)

1. Đăng nhập HassMind Web Admin bằng tài khoản quản trị.
2. Mở **Knowledge** → mục **Devices · Danh mục thiết bị** → **+ Thêm từ Home Assistant**.
3. Tìm thiết bị (tên, khu vực, Tuya, model…), lọc khu vực và chọn một mục từ danh sách.
4. Xem các entity, tên, device ID, trạng thái disabled/hidden trong Entity Registry. **Không hiển thị trạng thái on/off thực tế trong bảng này**.
5. Có thể sửa **Tên sử dụng trong HassMind** và thêm **Tên gọi khác** (mỗi dòng một tên).
6. Nhấn **Tạo đề xuất thêm Device**; xem **Review changes**, chạy **Dry-run**, sau đó nhấn **Approve** để lưu.
7. File được lưu vào `/knowledge/21-devices.yaml` (host bind mount theo Docker Stack), index lại tự động. Có thể Rollback đề xuất nếu cần.
8. Nhấn **Đồng bộ** để lấy danh sách HA Registry mới. Những Device đã thêm sẽ hiển thị **Đã có trong Knowledge**.

## File YAML được tạo

```yaml
schema_version: 1
kind: hassmind_device_catalog
devices:
  - key: o_cam_bom_nuoc_0123456789
    name: "Ổ cắm Bơm Nước"
    aliases:
      - "bơm nước"
    area: "Bếp"
    area_id: "kitchen"
    match:
      device_id: "EXAMPLE_DEVICE_ID_FROM_HA"
      manufacturer: "Tuya"
      model: "TS011F_plug_1"
    entities:
      mode: auto
      include_disabled: false
      include_hidden: false
```

`device_id` và tên `area_id` trong ví dụ chỉ để minh họa; khi chọn trên Web, HassMind sẽ đọc giá trị thật. Không cần khai báo `switch.*`, `sensor.*` thủ công.

**Lưu ý:** File `20-entities.yaml` cũ không bị xóa. Device Knowledge được đọc qua Device Registry, còn trạng thái Home Assistant thực tế phải truy vấn trực tiếp. Đây chưa phải cơ chế tự động cho phép điều khiển mọi entity của Device: service calls vẫn tuân theo policy + xác nhận mục tiêu hiện hành. Nếu có file 21-devices.yaml mẫu trước đây chưa điền device_id, luồng import có thể nâng cấp một dòng trùng duy nhất theo tên + hãng/model; nếu nhiều dòng trùng phải sửa thủ công.

## API & bảo mật

- `GET /api/knowledge/devices`: đăng nhập admin; đọc Device/Entity/Area Registry; không thay đổi HA.
- `POST /api/knowledge/devices/import`: admin + CSRF; yêu cầu Device tồn tại trong HA tại thời điểm gọi; tạo proposal chờ duyệt.
- Approval sử dụng expected_hash và index lại, có Rollback; không lưu state snapshot trong Knowledge.

## Triển khai Docker Stack

Hãy build/push image từ mã nguồn v1.5.2 này qua CI/GHCR của bạn, sau đó cập nhật image của service trong Docker Stack trên **Swarm manager**. Giữ nguyên các bind mounts `/data`, `/knowledge`, `/data/secrets` và các biến `HA_URL`/Home Assistant token. Chỉ giải nén ZIP trên host không tự thay đổi image đang chạy.
