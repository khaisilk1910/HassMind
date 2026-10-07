# QA HassMind v1.3.7

## Phạm vi rà soát

- Backend managed skills: overlay built-in/user, CRUD, enable/disable, validation, test, history và rollback.
- Bảo vệ storage: slug/path traversal, symbolic link, atomic write, read-only built-in và lỗi storage không ghi được.
- Web Admin Skills Manager: create/edit/test/toggle/delete/version/rollback, search/filter, validation result.
- Agent integration: disabled/invalid skill không xuất hiện trong `skill_list`; system prompt dùng skill cho workflow lặp lại.
- Deployment: `/data/skills`, biến `USER_SKILLS_DIR`, Docker/Stack/Portainer/setup.
- Validation toàn bộ skill Home Assistant cài sẵn và regression suite hiện có.

## Kết quả

- `python3 -m py_compile app/skills.py app/main.py app/settings.py`: **PASS**.
- `node --check static/app.js`: **PASS**.
- Python full suite: **159/159 PASS**.
- JavaScript UI suite: **27/27 PASS**.
- Skill management unit tests: **7/7 PASS**, gồm override/restore built-in, version/rollback, toggle, invalid skill, traversal và symlink rejection.
- 21 built-in Home Assistant skills: **21 valid, 0 invalid, 0 warning**.
- Kiểm tra deployment/config: version `1.3.7`, `USER_SKILLS_DIR=/data/skills` và volume `/data` giữ nguyên read-write.

## Ghi chú môi trường QA

Runner hiện tại không có package `openai` và `mcp` cài sẵn và không có mạng để tải dependency. Full Python suite được chạy với **import-only stubs tạm thời đặt ngoài source tree** cho hai package này; stubs không được đóng gói trong bản phát hành và không thực hiện network call. Các test managed-skills không phụ thuộc OpenAI/MCP thật. Image HassMind vẫn dùng dependency thật từ `requirements.txt` khi build trong môi trường có registry/network.
