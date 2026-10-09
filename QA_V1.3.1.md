# QA — HassMind 1.3.1 Knowledge approval fix

Kiểm thử ngày 04/10/2026. Source đầu vào: `hassmind-v1.3.0-knowledge-reviewed.zip`.

## Kết quả

- **128 test Python PASS**, 0 fail/error/skip trong lượt tổng hợp cuối.
- **18 test JavaScript PASS** bằng Node, gồm kiểm tra UI conflict detail, XSS escaping, CSRF, dry-run gate và Re-index approval.
- `python -m compileall -q app tests`: PASS.
- `node --check static/app.js`: PASS.
- `node --check static/login.js`: PASS.

Các test mới/được mở rộng xác nhận:

- `entity_conflict` trả về `conflict_fields`, `definitions`, `path` và `location` chính xác.
- `area_conflict` trả về area thực tế và các label hợp lệ của area_id.
- Re-index proposal có conflict warning vẫn `dry-run.valid=true`, có thể Approve và index vẫn giữ warning để người dùng xử lý sau.
- Content proposal không bị khóa bởi conflict warning ở file không liên quan, nhưng vẫn bị khóa nếu file đang sửa còn tham gia conflict.
- API thực tế `/dry-run` → `/approve` cho Re-index warning trả 200 và trạng thái `applied`.
- Review-only proposal không có nút Approve; diagnostic/diff/error vẫn được escape.

## Ghi chú môi trường QA

Container QA hiện không có package `openai` và `mcp` trong virtualenv và không có DNS để cài thêm. Bộ test đầy đủ được chạy bằng **import-only stubs** cho đúng hai package này để cho phép import `app.agent`/`app.mcp_client`; không stub logic Knowledge, database, FastAPI/TestClient, auth, Home Assistant safety boundary, filesystem, transaction hay UI. Các test Knowledge registry/governance/transaction/UI cũng đã chạy trực tiếp không cần hai dependency ngoài đó.

Chưa build Docker image và chưa kết nối Home Assistant thật trong môi trường QA này. Sau deploy nên chạy Scan → mở Re-index proposal → Dry-run → xác nhận warning được liệt kê chi tiết → Approve & Re-index.
