# HassMind v1.5.6 — Universal Session Conversation Context

## Cập nhật

- Mọi chủ đề chat Web/Zalo đều nhận lịch sử hội thoại cùng phiên. Hỏi tiếp, sửa lại, so sánh, giải thích và quay lại chủ đề cũ được AI hiểu theo lịch sử thay vì chỉ Device focus.
- Tầng Logic-First từ chối xử lý suy đoán cho câu có đại từ/phụ thuộc ngữ cảnh khi không có target chắc chắn; nhánh AI nhận câu hiện tại + lịch sử đúng phiên. Device follow-up đủ rõ vẫn chạy deterministic và đọc state mới.
- Lấy ngữ cảnh hai lớp: cửa sổ tin nhắn gần nhất (`AGENT_HISTORY_MESSAGES`, `ZALO_HISTORY_MESSAGES`) + tìm các trao đổi cũ có từ khóa liên quan từ SQLite; có giới hạn số tin nhắn quét, số trao đổi truy hồi và số ký tự.
- Khi cửa sổ chat bị rút ngắn do câu trả lời dài, truy hồi được phép quét cả những tin nhắn vừa bị loại do giới hạn độ dài.
- Sửa lọc lịch sử theo cả `session_id` và `source`; API khôi phục chat Web không trả về tin nhắn Zalo/system trong trường hợp trùng mã phiên.
- Scheduler và Event source=`system` luôn dùng duy nhất câu prompt hiện tại, không có lịch sử hội thoại.
- Tin nhắn trước chỉ là dữ liệu không đáng tin, không cấp quyền thao tác hoặc approve. State, dữ liệu ngoài theo thời gian phải kiểm tra nguồn hiện tại.
- Giữ nguyên bảng `session_device_focus`, Knowledge, giới hạn quyền và cách lưu lịch sử SQLite; chỉ thêm index `(session_id,source,id)` tự động khi khởi động.

## Cấu hình mặc định

| Biến | Mặc định | Chức năng |
|---|---:|---|
| `AGENT_HISTORY_MESSAGES` | 24 | Số tin nhắn gần nhất cho Web |
| `ZALO_HISTORY_MESSAGES` | 12 | Số tin nhắn gần nhất cho Zalo |
| `CONVERSATION_CONTEXT_MAX_CHARS` | 16000 | Tổng số ký tự ngữ cảnh gần nhất |
| `CONVERSATION_RECALL_EXCHANGES` | 4 | Số cặp hỏi/đáp cũ tối đa |
| `CONVERSATION_RECALL_SCAN_MESSAGES` | 1200 | Số tin nhắn cũ quét tối đa |
| `CONVERSATION_RECALL_MAX_CHARS` | 5000 | Kích thước phần hồi tưởng cũ |
| `CONVERSATION_FOCUS_MINUTES` | 60 | TTL riêng cho Device focus |

## Ví dụ

1. “Tạo Scheduler kiểm tra bơm nước” → “Cho chạy mỗi 30 phút” → hiểu đó là Scheduler trước, không phải một lịch độc lập.
2. “Viết mẫu thông báo điện thoại” → “Ngắn hơn, thêm emoji” → sửa đúng nội dung trước đó.
3. “Giải thích số điện năng” → “Tại sao lại tăng?” → trả lời dựa trên nội dung vừa trao đổi; trạng thái hiện tại cần đọc lại từ HA.
4. Sau nhiều lượt khác chủ đề: “Quay lại Scheduler bơm nước lúc nãy” → tìm lại trao đổi liên quan nếu nằm trong giới hạn truy hồi.
5. Tạo “Phiên mới”, hoặc chat từ Zalo khác → không dùng lại lịch sử phiên cũ.

## Giới hạn

Truy hồi theo từ khóa là deterministic (không embedding), không bảo đảm luôn tìm đúng chủ đề cũ nếu câu tham chiếu quá mơ hồ, tên chủ đề thay đổi hoàn toàn hoặc nằm ngoài giới hạn quét. Khi không chắc chắn HassMind cần hỏi lại. Chưa thử với AI backend/HA thực trong môi trường kiểm thử.
