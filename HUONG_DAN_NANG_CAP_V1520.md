# HassMind v1.5.20 — Cấu hình kết nối tập trung và khám phá API/MCP

## Nâng cấp an toàn từ v1.5.19

1. Sao lưu nguyên trạng thư mục `data/` (bao gồm SQLite và `data/secrets`), `.env`, thư mục `secrets/` nếu đang dùng, cùng các tệp Docker Compose/Stack của bạn.
2. Thay mã nguồn bằng v1.5.20, **giữ nguyên `data/`, `knowledge/`, `config/`, `.env` và Docker secrets cũ**; không xóa các volume dữ liệu.
3. Rebuild/redeploy container (`docker compose up -d --build` nếu sử dụng Compose). Cấu trúc dữ liệu được tự động nâng cấp, không xóa ghi chú và lịch sử.
4. Đăng nhập Web Admin → **Integrations** → **Kết nối hệ thống**:
   - **Home Assistant**: Home Assistant URL, Long-lived access token, HA notify service.
   - **OpenAI / LLM tương thích**: API Base URL, model, API key. Với local proxy không kiểm tra key, có thể để trống (ứng dụng sử dụng chuỗi giả để khởi tạo SDK).
   - **SearXNG**: URL tùy chọn; để trống để tắt tìm kiếm web.
5. Nhấn **Lưu & áp dụng**. HA REST client và subscription WebSocket được kết nối lại nếu URL/token thay đổi. OpenAI SDK cập nhật cho các lượt chat tiếp theo. Giá trị Web Admin được ưu tiên trước .env/Docker secret cũ; rollback bằng nút **Khôi phục stack/default**.

**Không bắt buộc sửa `.env`/stack của hệ thống đang chạy để đổi URL, model hoặc token HA/OpenAI.** Tuy nhiên Compose/Stack ban đầu vẫn có thể yêu cầu các file bootstrap cho tài khoản admin, API token và mount Docker secrets; đừng xóa chúng khi nâng cấp.

## Thêm dịch vụ HTTP container: tự động API Actions

1. Integrations → **Thêm Integration mới**. Điền tên, Base URL, Authentication và token (nếu có).
2. Bấm **Quét API**. HassMind chỉ gọi `GET` đến các đường dẫn mô tả chuẩn OpenAPI/Swagger thường dùng: `/openapi.json`, `/api/openapi.json`, `/swagger.json`, `/swagger/v1/swagger.json`, `/v3/api-docs`, `/api-docs`. Nếu API base có tiền tố `/v1`, hệ thống thử cả document tại gốc host.
3. Nếu tài liệu ở vị trí riêng, nhập **OpenAPI path**, ví dụ `/api/openapi.json`. Đường dẫn phải cùng service, không hỗ trợ tự tìm qua link ngoài.
4. HassMind chuyển các endpoint GET/POST/PUT/PATCH/DELETE và JSON schema tương thích thành các API Actions đã được điền phương thức, path, tham số và vị trí tham số (path/query/json). Những endpoint phức tạp/không hỗ trợ được bỏ qua và nêu cảnh báo.
5. Xem từng action. **Cho Agent sử dụng** mặc định **tắt** cho action mới phát hiện. Chỉ bật sau khi kiểm tra endpoint; sau đó bấm **Tạo Integration** hoặc **Lưu & áp dụng**. Form **JSON nâng cao** vẫn có để sửa ngoại lệ.

**Lưu ý:** Không thể lấy chính xác API Actions chỉ từ Base URL nếu container không công bố mô tả OpenAPI/Swagger. Khi đó phải cung cấp tài liệu API hoặc khai báo actions thủ công. Quét không tự gọi API nghiệp vụ. Bất kỳ thao tác làm thay đổi dữ liệu nào vẫn được gắn `mode=write` để áp dụng chính sách tác vụ của HassMind.

## Thêm MCP Server và lấy Agent Tools

Integrations → **MCP Servers** → **Thêm MCP Server**: điền ID, URL Streamable HTTP (thường kết thúc `/mcp`), Bearer hoặc API-key header. Nhấn **Quét MCP Tools** để thực hiện handshake MCP và gọi `tools/list` (không thực hiện `tools/call`). Danh sách tool có mô tả sẽ hiện ra; đánh dấu **Cho Agent sử dụng** cho từng tool rồi lưu. Tool chưa được duyệt sẽ bị từ chối tại `mcp_call`.

MCP server mới được lưu SQLite và credential nằm trong `data/secrets`; cấu hình MCP YAML cũ vẫn chạy để tương thích. Khi ID của một cấu hình Web Admin trùng server YAML, Web Admin được ưu tiên; ngay cả khi bạn tắt server trong Web Admin, ID trùng cũng không tự quay về YAML để vượt kiểm soát quyền.

## Các giới hạn và lưu ý triển khai

- Chỉ các hệ thống HTTP có OpenAPI/Swagger và MCP Streamable HTTP có thể được khám phá theo hai cơ chế này; không hỗ trợ tự nhận diện gRPC, SOAP tùy ý, WebSocket custom, MCP stdio hoặc HTTP API không công bố schema.
- Discovery yêu cầu container HassMind truy cập tới server trên mạng. Với **host networking** có thể dùng `http://127.0.0.1:PORT`; với Docker bridge network thường cần hostname service/container, vì `127.0.0.1` của container không phải container khác.
- Discovery không follow HTTP redirects, có timeout, giới hạn 3MB OpenAPI, giới hạn 24 API Actions/integration. Chặn URL metadata/link-local/multicast để hạn chế request tới đích nguy hiểm. Các server bạn nhập phải đáng tin cậy.
- Credential không trả về qua API; để trống khi sửa để giữ nguyên. Nhớ bảo vệ quyền truy cập Web Admin và sao lưu `data/secrets` cùng DB.
- SearXNG chỉ cấu hình URL; nếu server không hỗ trợ `/search?format=json`, Web Search sẽ không hoạt động.
- **Chưa thực hiện kiểm thử trực tiếp trên thiết bị Home Assistant và container cụ thể của bạn**. Hãy thử kết nối, gửi một truy vấn đọc trước, rồi mới bật các tool có quyền ghi.
