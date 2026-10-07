# HassMind 1.3.1 — Knowledge dry-run, conflict diagnostics và approval fix

Bản 1.3.1 tập trung sửa luồng Review/Dry-run/Approve của Knowledge mà không thay đổi cơ chế an toàn điều khiển Home Assistant.

- **Chi tiết xung đột rõ ràng:** `entity_conflict`, `alias_conflict`, `area_alias_conflict`, `area_conflict` và `domain_conflict` trả về entity/alias liên quan, trường đang khác nhau, file và vị trí record như `entities[2]`, cùng các định nghĩa cụ thể để đối chiếu.
- **Không còn cảnh báo trùng lặp mơ hồ:** một `entity_conflict` được gom thành một diagnostic có danh sách toàn bộ định nghĩa xung đột thay vì nhiều dòng giống nhau.
- **Sửa Re-index không Approve được:** warning-level ambiguity (entity/alias/area conflict) vẫn được hiển thị nhưng **không chặn** proposal kiểu `reindex`. Chỉ lỗi cấu trúc/file/index, stale proposal hoặc lỗi thực sự mới chặn.
- **Content proposal chặn đúng phạm vi:** xung đột warning chỉ chặn khi file đang sửa tham gia xung đột. Xung đột ở file không liên quan vẫn được cảnh báo nhưng không khóa một thay đổi an toàn khác.
- **Review proposal được phân biệt rõ:** proposal kiểu `review` là phiếu cảnh báo, không còn hiển thị nút Approve gây hiểu nhầm. Người dùng cần sửa file/tạo content proposal cụ thể.
- **UI Dry-run nâng cấp:** hiển thị `chặn áp dụng` hay `warning`, số cảnh báo không chặn, các record xung đột, name/area/domain của từng record và nút `Approve & Re-index` khi phù hợp.
- **Backend vẫn tự kiểm tra lại khi Approve:** UI chỉ là gate tiện dụng; backend tiếp tục chạy lại dry-run, kiểm tra fingerprint/hash và re-index transactional trước khi hoàn tất.

Không tự đổi entity_id, alias, name hoặc area của người dùng. Các ambiguity vẫn làm `safe_for_control=false` cho đến khi được sửa hoặc disambiguate theo area/domain.
