# HassMind 1.3.0 — Knowledge semantic registry và duyệt thay đổi

- Registry entity/area/scene/script/reference/rules/procedures; metadata, alias tiếng Việt, confidence, ambiguity, exact/name/area-domain/fuzzy priority và lọc search. Giữ file format/API cũ.
- Knowledge tĩnh tách khỏi state HA realtime. Chặn fuzzy/ambiguous/ID sao chép từ tài liệu ở tool routing và HA service boundary, giữ quyền domain và explicit user target cũ.
- Index transactional, manifest/hash/errors, giữ index tốt khi input lỗi; UI hiển thị loại/score/ID/phòng/domain/source/preview và trạng thái re-index.
- Monitor định kỳ, đối chiếu registry HA, phát hiện file thay đổi/schema/xung đột/unresolved. Tạo proposal/diff và thông báo; chỉ admin Approve mới apply.
- Dry-run, fingerprint/hash chống stale, backup nguyên byte, rollback có guard, journal khôi phục sau crash và audit. Agent không có tool duyệt/apply.
- UI Scan/Review/Dry-run/Approve/Reject/Rollback/Re-index, form sửa source thành draft; config persist và CSRF.
- Sample ngoài live Knowledge, hướng dẫn migrate/permissions/Compose override, test registry/routing/proposal/transaction/API/UI và startup smoke.

Xem `KNOWLEDGE_MIGRATION_VI.md` trước khi triển khai; `QA_V1.3.0.md` ghi kết quả kiểm thử và các giới hạn.
