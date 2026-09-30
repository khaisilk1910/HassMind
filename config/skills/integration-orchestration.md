# Integration orchestration

Dùng skill này khi một yêu cầu cần phối hợp các container/custom component đã tích hợp vào HassMind.

## Nguyên tắc

1. Kiểm tra `integrations_status` cho Camera TTS, FaceDetect, Zalo, Wyoming khi nghi ngờ dịch vụ ngoài chưa sẵn sàng.
2. Kiểm tra `ha_custom_integrations_status` cho EVN, Âm lịch, Shopping History và yt_dlp.
3. Ưu tiên dữ liệu đọc trước, sau đó mới thực hiện hành động.
4. Không thay typed adapter bằng `ha_call_service` để né policy.
5. Nếu thao tác bị policy chặn, báo rõ tên biến cấu hình cần operator bật; không tìm đường vòng.

## Luồng gợi ý

- Nhận diện/ngữ cảnh camera: `facedetect_summary` / `facedetect_events` -> kiểm tra ngữ cảnh HA -> nếu thật sự cần phát loa camera thì `camera_tts_say`.
- Điện: `evn_accounts` -> `evn_summary` hoặc `evn_daily`/`evn_monthly` -> so sánh với state/history HA nếu cần.
- Lịch Việt: `lunar_convert_date` cho phép đổi ngày dương/âm thông qua service response của HA.
- Mua sắm: `shopping_profiles` -> `shopping_list`; add/edit/delete chỉ khi policy mutation tương ứng đã bật.
- Media: `yt_dlp_search` -> `yt_dlp_play`; download cần policy riêng và nên trả job ID để theo dõi bằng `yt_dlp_get_job`.
- TTS tiếng Việt Wyoming: `ha_tts_speak`; nếu có nhiều `tts.*` entity thì truyền rõ `tts_entity_id`.
- Zalo: `zalo_accounts` trước nếu có nhiều tài khoản; giữ `thread_id`/`account_selection` dưới dạng string. Auto-reply inbound chỉ hợp lệ với thread nằm trong allowlist backend.

## An toàn

Không đưa token/password/API key vào prompt, memory, knowledge hoặc arguments tool. Các secret chỉ được backend đọc từ Docker secrets/environment.
