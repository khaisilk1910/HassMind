# QA — HassMind 1.3.4 timezone consistency

## Kiểm thử tự động

- `python -m compileall -q app`: PASS.
- Python test suite: **151 passed + 12 subtests passed**.
- JavaScript UI suite: **23/23 passed**.
- Tất cả file YAML stack/compose parse thành công với PyYAML.
- Scan source xác nhận không còn `datetime.now(timezone.utc)`, `datetime.utcnow()` hoặc hard-coded `timezone.utc` trong `app/`.

## Kiểm thử timezone bổ sung

- `now_iso()` với `Asia/Ho_Chi_Minh` trả offset `+07:00`.
- Timestamp legacy `2026-10-04T11:27:57.027022+00:00` được chuyển thành `2026-10-04T18:27:57.027022+07:00`.
- Scheduler interval với input UTC trả `next_run` ở timezone cấu hình.
- Scheduler daily `21:00` được hiểu là 21:00 theo timezone cấu hình.
- Timestamp cũ trong `jobs.next_run`, `jobs.last_run`, `created_at` được normalize tự động.
- Timestamp nhúng trong Knowledge index/scan JSON được normalize cùng các cột SQLite.
- UI formatter giữ offset server và không phụ thuộc timezone của browser.

## Lưu ý triển khai

Sau build/deploy, kiểm tra:

```sh
docker exec hassmind date
docker exec hassmind sh -lc 'printf "TZ=%s TIMEZONE=%s\\n" "$TZ" "$TIMEZONE"'
```

Với cấu hình mặc định mong đợi, cả hai biến là `Asia/Ho_Chi_Minh` và `date` hiển thị giờ địa phương UTC+7. `/health` cũng trả trường `timezone`.
