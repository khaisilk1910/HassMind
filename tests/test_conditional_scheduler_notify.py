import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app import main
from app.agent import Agent
from app.notifications import NO_NOTIFY_TOKEN, action_only_notification_prompt, actionable_notification_prompt, always_notification_prompt


class _Agent:
    def __init__(self, result):
        self.result = result

    async def chat(self, session_id, prompt, source="system"):
        return self.result




class _TraceAgent:
    def __init__(self, result, tools):
        self.result = result
        self.tools = tools

    async def chat_with_trace(self, session_id, prompt, source="system"):
        return {"text": self.result, "tools": self.tools}


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


    def test_system_scheduler_turn_does_not_reuse_prior_session_history(self):
        class _Message:
            content = "__HASSMIND_NO_NOTIFY__"
            tool_calls = None

        class _Choice:
            message = _Message()
            finish_reason = "stop"

        class _Response:
            choices = [_Choice()]
            usage = None
            id = "test-response"

        class _Completions:
            async def create(self, **kwargs):
                user_messages = [m for m in kwargs["messages"] if m.get("role") == "user"]
                self.seen = user_messages
                return _Response()

        class _Chat:
            def __init__(self):
                self.completions = _Completions()

        class _Client:
            def __init__(self):
                self.chat = _Chat()

        agent = Agent.__new__(Agent)
        agent.runtime = object()
        agent.system_prompt = "system"
        agent.client = _Client()
        with patch("app.agent.add_message"), patch("app.agent.get_messages", side_effect=AssertionError("system runs must be stateless")), patch("app.agent.schemas", return_value=[]):
            result = asyncio.run(agent.chat("job:3", "CURRENT JOB PROMPT", source="system"))
        self.assertEqual(result, "__HASSMIND_NO_NOTIFY__")
        self.assertEqual(agent.client.chat.completions.seen, [{"role": "user", "content": "CURRENT JOB PROMPT"}])

    def test_actionable_mode_suppresses_provider_capability_refusal_without_tool_evidence(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _TraceAgent("Tôi là một mô hình ngôn ngữ nên điều đó nằm ngoài khả năng của tôi.", [])
            main.ha = object()
            main.integrations = object()
            prompt = actionable_notification_prompt("Kiểm tra thiết bị")
            with patch.object(main, "send_notification", new=AsyncMock()) as send:
                result = asyncio.run(main.run_prompt("job:3", prompt, True, "zalo", "thread-1"))
            self.assertEqual(result, "🔕 Không có nội dung cần thông báo.")
            send.assert_not_awaited()
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations

    def test_actionable_mode_sends_short_result_when_side_effect_tool_succeeded(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _TraceAgent(
                "Quạt trần phòng Sóc Chíp: off",
                [{"tool": "ha_call_service", "status": "ok", "read_only": False, "side_effect": True}],
            )
            main.ha = object()
            main.integrations = object()
            prompt = actionable_notification_prompt("Tắt quạt khi phòng vắng")
            with patch.object(main, "send_notification", new=AsyncMock(return_value={"ok": True})) as send:
                result = asyncio.run(main.run_prompt("job:3", prompt, True, "zalo", "thread-1"))
            self.assertEqual(result, "Quạt trần phòng Sóc Chíp: off")
            send.assert_awaited_once()
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations

    def test_actionable_mode_suppresses_hallucinated_success_without_side_effect_evidence(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _TraceAgent("Đã tắt quạt phòng khách.", [])
            main.ha = object()
            main.integrations = object()
            prompt = actionable_notification_prompt("Kiểm tra thiết bị")
            with patch.object(main, "send_notification", new=AsyncMock()) as send:
                result = asyncio.run(main.run_prompt("job:3", prompt, True, "zalo", "thread-1"))
            self.assertEqual(result, "🔕 Không có nội dung cần thông báo.")
            send.assert_not_awaited()
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations

    def test_action_only_mode_suppresses_warning_without_successful_action(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _TraceAgent(
                "Sensor hiện diện unavailable và cần kiểm tra.",
                [{"tool": "ha_get_states", "status": "ok", "read_only": True, "side_effect": False}],
            )
            main.ha = object()
            main.integrations = object()
            prompt = action_only_notification_prompt("Chỉ báo khi tắt thành công")
            with patch.object(main, "send_notification", new=AsyncMock()) as send:
                result = asyncio.run(main.run_prompt("job:3", prompt, True, "zalo", "thread-1"))
            self.assertEqual(result, "🔕 Không có nội dung cần thông báo.")
            send.assert_not_awaited()
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations

    def test_action_only_mode_sends_only_after_successful_side_effect(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _TraceAgent(
                "Quạt trần phòng Sóc Chíp: off",
                [{
                    "tool": "ha_call_service", "status": "ok", "read_only": False, "side_effect": True,
                    "arguments": {"domain": "switch", "service": "turn_off", "target": {"entity_id": "switch.ct4_phong_soc_chip_l3"}},
                }],
            )
            main.ha = object()
            main.integrations = object()
            prompt = action_only_notification_prompt("Chỉ báo khi tắt thành công")
            with patch.object(main, "send_notification", new=AsyncMock(return_value={"ok": True})) as send:
                result = asyncio.run(main.run_prompt("job:3", prompt, True, "zalo", "thread-1"))
            self.assertEqual(result, "Quạt trần phòng Sóc Chíp: off")
            send.assert_awaited_once()
        finally:
            main.agent, main.ha, main.integrations = old_agent, old_ha, old_integrations

    def test_action_only_mode_recovers_when_model_returns_silent_token_after_action(self):
        old_agent, old_ha, old_integrations = main.agent, main.ha, main.integrations
        try:
            main.agent = _TraceAgent(
                NO_NOTIFY_TOKEN,
                [{
                    "tool": "ha_call_service", "status": "ok", "read_only": False, "side_effect": True,
                    "arguments": {"domain": "switch", "service": "turn_off", "target": {"entity_id": "switch.test_fan"}},
                }],
            )
            main.ha = object()
            main.integrations = object()
            prompt = action_only_notification_prompt("Chỉ báo khi tắt thành công")
            with patch.object(main, "send_notification", new=AsyncMock(return_value={"ok": True})) as send:
                result = asyncio.run(main.run_prompt("job:3", prompt, True, "zalo", "thread-1"))
            self.assertIn("switch.turn_off", result)
            self.assertIn("switch.test_fan", result)
            send.assert_awaited_once()
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
