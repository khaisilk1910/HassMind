# QA — HassMind v1.5.0 Logic-First Core

## Phạm vi kiểm thử

- Logic-first exact entity state query.
- Deterministic direct control + verification.
- Friendly-name exact resolution và ambiguity clarification.
- Conditional/semantic request fallback sang AI.
- Job 3 vacancy profile: presence gate, TV veto, area registry mapping, switch allowlist, verified action only.
- Legacy Job 3 auto-routing.
- Event context không làm nhiễm action target.
- Runtime repeated-failure memory và retry guard.
- Scheduler concurrency.
- Event rule concurrency.
- Regression toàn bộ suite cũ.
- JavaScript UI regression và syntax.

## Safety invariants

- Không action theo fuzzy room mapping trong logic profile.
- Switch không rõ load không được tự suy luận từ friendly name.
- Direct side effect chỉ báo thành công sau fresh-state verification.
- Yêu cầu mơ hồ có entity trùng tên hỏi lại thay vì chọn ngẫu nhiên.
- Repeated deterministic failure được lưu và tránh retry mù.
- `action_only` vẫn là notification gate cuối cho Job 3.

## Kết quả

- Python: **213 passed**.
- Python subtests: **12 passed**.
- JavaScript UI: **31/31 passed**.
- `python -m compileall -q app`: **PASS**.
- `node --check static/app.js`: **PASS**.
- Built-in skills: **22**, invalid **0**, warning **0**.
- Logic profiles JSON: **PASS**.
- ZIP integrity được kiểm tra ở bước phát hành và ghi trong `RELEASE_MANIFEST.json`.
