import unittest

from app.integrations.base import IntegrationError
from app.integrations.zalo import ZaloClient


class StubZaloClient(ZaloClient):
    def __init__(self):
        self.sent = None

    async def ensure_login(self) -> None:
        return None

    async def _select_account(self, requested: str = "") -> str:
        return requested or "account-1"

    async def request(self, method, path, **kwargs):
        self.sent = {"method": method, "path": path, **kwargs}
        return {"success": True}


class RejectStylesZaloClient(StubZaloClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def request(self, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, **kwargs})
        if len(self.calls) == 1:
            raise IntegrationError("HTTP 422 from http://zalo/api/sendMessageByAccount: styles unsupported")
        self.sent = self.calls[-1]
        return {"success": True}


class ZaloTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_message_posts_plain_msg_plus_styles(self):
        client = StubZaloClient()
        await client.send_message(
            thread_id="zalo:123",
            message="# Tiêu đề\n- **Thiết bị:** {green}**Bật**{/green}",
            thread_type=1,
            account_selection="acc",
        )
        body = client.sent["json"]
        self.assertEqual(client.sent["path"], "/api/sendMessageByAccount")
        self.assertEqual(body["threadId"], "123")
        self.assertEqual(body["accountSelection"], "acc")
        self.assertEqual(body["message"]["msg"], "Tiêu đề\nThiết bị: Bật")
        self.assertNotIn("**", body["message"]["msg"])
        self.assertNotIn("#", body["message"]["msg"])
        styles = body["message"]["styles"]
        self.assertTrue(any(x["st"] == "f_18" for x in styles))
        self.assertTrue(any(x["st"] == "lst_1" for x in styles))
        self.assertTrue(any(x["st"] == "c_15a85f" for x in styles))

    async def test_explicit_schema_rejection_falls_back_to_plain_text_without_markers(self):
        client = RejectStylesZaloClient()
        await client.send_message(
            thread_id="123",
            message="### **Trạng thái:** {green}**Tốt**{/green}",
            thread_type=1,
            account_selection="acc",
        )
        self.assertEqual(len(client.calls), 2)
        fallback_message = client.calls[1]["json"]["message"]
        self.assertEqual(fallback_message, {"msg": "Trạng thái: Tốt"})


if __name__ == "__main__":
    unittest.main()
