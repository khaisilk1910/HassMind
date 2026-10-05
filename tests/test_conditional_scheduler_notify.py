import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app import main
from app.notifications import NO_NOTIFY_TOKEN, actionable_notification_prompt, always_notification_prompt


class _Agent:
    def __init__(self, result):
        self.result = result

    async def chat(self, session_id, prompt, source="system"):
        return self.result


class ConditionalSchedulerNotifyTests(unittest.TestCase):
    def test_run_prompt_suppresses_exact_no_notify_token(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _Agent(NO_NOTIFY_TOKEN)
            main.ha = object()
            main.integrations = object()
            with patch.object(main, "send_notification", new=AsyncMock()) as send:
                result = asyncio.run(main.run_prompt("job:99", "check", True, "mobile", ""))
            self.assertEqual(result, "🔕 Không có nội dung cần thông báo.")
            send.assert_not_awaited()
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations

    def test_run_prompt_cleans_malformed_always_result_before_send_and_storage(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            raw = r"*(Theo đúng yêu*(Hệ thống không ghi nhận đèn hoặc quạt nào đang bật tại khu vực vắng người cần thao tác tắt, đúng theo điều kiện không gửi thông báo).\*"
            expected = "✅ Hệ thống không ghi nhận đèn hoặc quạt nào đang bật tại khu vực vắng người cần thao tác tắt."
            main.agent = _Agent(raw)
            main.ha = object()
            main.integrations = object()
            with patch.object(main, "send_notification", new=AsyncMock(return_value={"ok": True})) as send:
                result = asyncio.run(main.run_prompt("job:100", "check", True, "mobile", ""))
            self.assertEqual(result, expected)
            self.assertEqual(send.await_args.args[2], expected)
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations


    def test_actionable_mode_suppresses_natural_language_noop_fallback(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _Agent("✅ Không phát hiện thiết bị nào cần xử lý.")
            main.ha = object()
            main.integrations = object()
            prompt = actionable_notification_prompt("Kiểm tra thiết bị")
            with patch.object(main, "send_notification", new=AsyncMock()) as send:
                result = asyncio.run(main.run_prompt("job:8", prompt, True, "zalo", "thread-1"))
            self.assertEqual(result, "🔕 Không có nội dung cần thông báo.")
            send.assert_not_awaited()
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations

    def test_actionable_mode_does_not_hide_noop_text_when_warning_is_present(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _Agent("Không phát hiện thiết bị nào cần xử lý, nhưng sensor nhiệt độ unavailable và cần kiểm tra.")
            main.ha = object()
            main.integrations = object()
            prompt = actionable_notification_prompt("Kiểm tra thiết bị")
            with patch.object(main, "send_notification", new=AsyncMock(return_value={"ok": True})) as send:
                result = asyncio.run(main.run_prompt("job:8", prompt, True, "zalo", "thread-1"))
            self.assertIn("unavailable", result)
            send.assert_awaited_once()
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations

    def test_always_mode_keeps_natural_language_noop_notification(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _Agent("✅ Không phát hiện thiết bị nào cần xử lý.")
            main.ha = object()
            main.integrations = object()
            prompt = always_notification_prompt("Kiểm tra thiết bị")
            with patch.object(main, "send_notification", new=AsyncMock(return_value={"ok": True})) as send:
                result = asyncio.run(main.run_prompt("job:8", prompt, True, "zalo", "thread-1"))
            self.assertEqual(result, "✅ Không phát hiện thiết bị nào cần xử lý.")
            send.assert_awaited_once()
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations

    def test_actionable_prompt_has_no_conflicting_noop_sentence_instruction(self):
        prompt = actionable_notification_prompt("Kiểm tra thiết bị")
        self.assertIn(NO_NOTIFY_TOKEN, prompt)
        self.assertNotIn("'✅ Không phát hiện thiết bị nào cần xử lý.'", prompt)

    def test_run_prompt_still_sends_normal_result(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _Agent("Đã tắt quạt phòng khách")
            main.ha = object()
            main.integrations = object()
            with patch.object(main, "send_notification", new=AsyncMock(return_value={"ok": True})) as send:
                result = asyncio.run(main.run_prompt("job:99", "check", True, "mobile", ""))
            self.assertEqual(result, "Đã tắt quạt phòng khách")
            send.assert_awaited_once()
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations


if __name__ == "__main__":
    unittest.main()
