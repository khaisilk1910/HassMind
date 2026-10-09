# QA — HassMind v1.5.1 Logic-First Recovery

## Automated tests

- Python: **218 passed**
- Python subtests: **12 passed**
- JavaScript UI: **31 passed**
- `python -m py_compile`: PASS cho các module thay đổi
- `node --check static/app.js`: PASS

> Môi trường QA offline không có package `openai`/`mcp` cài từ PyPI, vì vậy full pytest được chạy với import stubs chỉ để thỏa dependency import. Không có network/model call nào được giả lập là thành công.

## Regression cases đã thêm

1. `xem trạng thái phòng ngủ` -> Logic Engine, một HA snapshot, không gọi AI.
2. Climate `state=off` + target cũ 25°C -> báo `off`, không nói đang bật 25°C.
3. Gọi `bedroom-climate-comfort` từ Web Chat -> route Logic Profile, không AI fallback.
4. Dry Run phòng nóng -> planned `cool 27°C` + fan action; **0 action executed**.
5. Dry Run không bao giờ lập target 25/26°C.
6. Generic model capability refusal cho HA intent -> bị backend thay bằng clarification ngắn gọn.
7. Scheduler concurrency và Advanced Scheduler regression tests vẫn PASS.

## Expected behavior sau fix

- Dry Run card phải có `Engine: ⚙ Logic` cho `bedroom-climate-comfort`.
- `Read-only tool đã chạy` >= 1 khi HA snapshot được đọc.
- Phòng nóng có người + climate off -> Action dự kiến gồm bật `cool`, target 27°C và fan theo band.
- Web Chat `xem trạng thái phòng ngủ` phải trả state realtime trong vài ms đến thời gian HA snapshot, không chờ 1 vòng LLM ~10–15 giây.
