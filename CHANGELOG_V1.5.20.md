# v1.5.20 (2026-10-14)

- Thêm cấu hình **Home Assistant URL/token/notify service**, **OpenAI-compatible base URL/model/key** và **SearXNG** trong Integrations Web Admin. Ưu tiên override ở SQLite và runtime secrets, vẫn hỗ trợ cấu hình legacy.
- Cho phép bootstrap Web Admin khi HA/LLM token chưa cấu hình; URL và token được áp dụng lại mà không cần rebuild stack. HA REST+WebSocket được kết nối lại, Agent khởi tạo OpenAI SDK mới.
- Auto-discover OpenAPI/Swagger JSON qua đường dẫn chuẩn hoặc đường dẫn do admin cung cấp; parse tham số path/query/JSON body, bỏ qua endpoint không hỗ trợ, không tự cấp quyền Agent.
- Editor Custom HTTP Actions có danh sách trực quan, bật/tắt action và Agent tool; JSON nâng cao vẫn dùng được.
- Thêm MCP Streamable HTTP connections qua Web Admin, `tools/list` discovery và per-tool allowlist cho `mcp_call`.
- Bảo tồn server MCP YAML cũ để tương thích, với Web Admin connection (kể cả disabled) có quyền ghi đè ID trùng.
- Cải thiện bảo mật: secrets tách riêng, API chỉ dùng admin auth, discovery chỉ truy vấn mô tả, giới hạn kích thước và timeout, không theo redirect, hạn chế đích metadata/link-local.
- Kế thừa toàn bộ chức năng ghi chú/Zalo/Knowledge/Skills của v1.5.19.
