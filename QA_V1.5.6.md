# QA HassMind v1.5.6

## Tự động (môi trường không có openai / mcp)

- Python compileall: đạt.
- Python unit/integration độc lập AI SDK: 216 passed, 12 subtests passed (chạy lại khi release).
- JavaScript node --test: 33 passed (chạy lại khi release).
- Không chạy được các module import SDK `openai` / `mcp`: cần kiểm thử tích hợp sau khi cài đủ thư viện.

## Các case kiểm thử mới

- Hỏi nối tiếp mọi chủ đề; tìm lại một trao đổi Scheduler cũ sau nhiều câu khác chủ đề.
- Giới hạn ngữ cảnh khi assistant trả lời rất dài, ưu tiên giữ nguyên câu hiện tại.
- Tách Web/Zalo/system theo session_id + source; không lấy chat của phiên khác.
- Guard câu nối tiếp có đại từ khi không có Device chắc chắn, không tự phát lệnh HA.
- AI prompt nhận lịch sử gần nhất và các trao đổi cũ trong cùng phiên, nhắc rõ ngữ cảnh cũ không là lệnh hoặc state live.
- Phần device report/follow-up và logic cũ không bị hồi quy.

## Cần kiểm tra sau deploy

1. Chat Web: “Giải thích Scheduler”, “Cho ví dụ”, “Ngắn hơn” phải tham chiếu câu trước.
2. Chat Web: “Tạo mẫu tin nhắn báo trạng thái”, “Thêm emoji”, “Bỏ dòng cuối” — không lạc chủ đề.
3. Sau 20–30 lượt khác: “Quay lại Scheduler bơm nước” kiểm tra hiểu ngữ cảnh cũ.
4. Đổi sang “Dự báo thời tiết” rồi hỏi tiếp, kiểm tra không lấy nhầm Device.
5. Mở “Phiên mới” — AI không kể lại chat cũ.
6. Zalo ở một thread khác phải tách ngữ cảnh; Scheduler/Event không dùng chat.
7. Hỏi lệnh điều khiển bằng đại từ khi nhiều entity phù hợp phải hỏi lại, không hành động sai.
8. Đối chiếu log và Home Assistant để xác minh đọc state luôn là mới.
