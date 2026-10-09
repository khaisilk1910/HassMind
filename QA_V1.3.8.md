# QA HassMind v1.3.8

## Phạm vi rà soát

- Hotfix layout trang Skills theo ảnh lỗi thực tế.
- Grid 12 cột, breakpoint responsive, vùng scroll và cache busting asset.
- Regression managed-skills backend và toàn bộ test suite hiện có.
- Validation 21 built-in Home Assistant skills.

## Kết quả

- `python3 -m pytest -q` với import-only stubs ngoài source tree: **168 passed + 12 subtests passed**.
- JavaScript UI suite: **27/27 PASS**.
- `node --check static/app.js` và `node --check static/login.js`: **PASS**.
- Skills focused tests: **10/10 PASS** (7 backend management + 3 layout regression).
- 21 built-in Home Assistant skills: **21 valid, 0 invalid, 0 warning**.
- CSS regression: `.span-7`, `.span-5`, responsive stack <=1280px, `min-width:0`, full-width skill list và asset query `?v=1.3.8`: **PASS**.

## Nguyên nhân lỗi đã xác định

HTML trang Skills dùng `span-7` và `span-5`, nhưng stylesheet v1.3.7 chỉ định nghĩa `span-12`, `span-8`, `span-6`, `span-4`, `span-3`. Trên desktop, hai card vì vậy chỉ chiếm một grid track mặc định và bị co thành cột rất hẹp.

## Ghi chú môi trường QA

Runner không có package `openai` và `mcp` cài sẵn. Full Python suite dùng import-only stubs tạm thời tại `/tmp`, ngoài source tree; stubs không nằm trong ZIP phát hành và không thực hiện network call. Image HassMind vẫn cài dependency thật từ `requirements.txt` khi build.
