# HassMind v1.2.5 — QA report

## Phạm vi

- Zalo plain-text formatter và FollowUp conversion.
- Zalo long-message splitting.
- Home Assistant live state cache/fallback.
- `ha_search_states` / `ha_get_states` helpers.
- Version/static cache-busting.
- Python, JavaScript, shell và YAML syntax.

## Kiểm thử tự động

`python -m unittest discover -s tests -v`:

- Markdown heading/bold/backtick/FollowUp -> Zalo plain text: PASS.
- Double-backtick và Home Assistant entity IDs có `_`: PASS.
- Long Zalo message split đúng giới hạn: PASS.
- Tìm `phòng ngủ` bằng query không dấu `phong ngu`: PASS.
- Domain/state filter: PASS.
- Compact custom scalar attributes và loại bỏ string quá lớn: PASS.
- HA state snapshot được reuse: PASS.
- HA `state_changed` update cache in-memory: PASS.
- Cache invalidation bắt buộc refresh: PASS.

## Static QA

- `python -m compileall`: PASS.
- `node --check static/app.js` và `static/login.js`: PASS.
- YAML parse cho stack/compose/MCP config: PASS.
- `bash -n setup.sh`: PASS.
- Version sync backend/frontend/VERSION: PASS (`1.2.5`).

## Ghi chú hiệu năng

QA xác nhận số REST state fetch trùng lặp được loại bỏ ở tầng code và các read-only tool calls có đường thực thi song song. Thời gian end-to-end thực tế còn phụ thuộc model OpenAI-compatible đang dùng, tốc độ host Home Assistant, số entity, mạng và độ dài câu trả lời; không ghi một con số latency cố định khi chưa benchmark trực tiếp trên server của người vận hành.
