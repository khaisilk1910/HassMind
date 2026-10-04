---
name: integration-orchestration
description: Phối hợp các integration HassMind và Home Assistant như Zalo, Camera
  TTS, FaceDetect, EVN, Âm lịch, Shopping, yt_dlp và Wyoming.
---

# Objective
Chọn đúng typed adapter, kiểm tra health khi cần và giữ policy của từng integration.

# Workflow
1. Dùng `integrations_status` cho Camera TTS, FaceDetect, Zalo, Wyoming khi nghi ngờ dịch vụ ngoài chưa sẵn sàng.
2. Dùng `ha_custom_integrations_status` cho EVN, Âm lịch, Shopping History và yt_dlp.
3. Ưu tiên dữ liệu đọc trước, sau đó mới thực hiện action.
4. Camera/nhận diện: `facedetect_summary` hoặc `facedetect_events` -> ngữ cảnh HA -> `camera_tts_say` khi thực sự cần.
5. Điện: `evn_accounts` -> `evn_summary`/`evn_daily`/`evn_monthly`.
6. Lịch Việt: dùng `lunar_convert_date` cho chuyển đổi âm/dương.
7. Media: `yt_dlp_search` -> `yt_dlp_play`; download chỉ khi policy riêng cho phép.
8. TTS tiếng Việt: ưu tiên `ha_tts_speak`; truyền `tts_entity_id` khi cần phân giải rõ.
9. Zalo: giữ `thread_id`/account ID dưới dạng string và tuân thủ allowlist/policy send.

# Safety rules
Không đưa token/password/API key vào prompt, memory, Knowledge hoặc tool arguments. Không dùng `ha_call_service` để né typed adapter/policy.
