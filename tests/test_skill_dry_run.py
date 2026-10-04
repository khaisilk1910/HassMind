import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent import Agent
from app.settings import settings
from app.skills import compose_skill


class _ToolCall:
    def __init__(self, call_id, name, args):
        self.id = call_id
        self.function = types.SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False))


class _Response:
    def __init__(self, content="", tool_calls=None):
        msg = types.SimpleNamespace(content=content, tool_calls=tool_calls or [])
        self.choices = [types.SimpleNamespace(message=msg, finish_reason="stop")]


class _Completions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if not self.responses:
            raise AssertionError("Unexpected extra LLM request")
        return self.responses.pop(0)


class _Client:
    def __init__(self, responses):
        self.chat = types.SimpleNamespace(completions=_Completions(responses))


class _Runtime:
    def __init__(self):
        self.calls = []
        self.integrations = types.SimpleNamespace(camera_tts=None, zalo=None, custom_tools={})

    async def call(self, name, args):
        self.calls.append((name, args))
        if name == "ha_search_states":
            return [{"entity_id": "light.test_room", "state": "on"}]
        raise AssertionError(f"Dry run must not execute side-effect tool: {name}")


class SkillScenarioDryRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_builtin = settings.skills_dir
        self.old_user = settings.user_skills_dir
        self.builtin = Path(self.tmp.name) / "builtin"
        self.user = Path(self.tmp.name) / "user"
        self.builtin.mkdir(parents=True)
        settings.skills_dir = str(self.builtin)
        settings.user_skills_dir = str(self.user)
        (self.builtin / "presence-aware-control.md").write_text(
            compose_skill(
                "presence-aware-control",
                "Điều khiển đèn và quạt theo hiện diện và trạng thái Home Assistant thực tế.",
                "# Objective\nKiểm tra hiện diện trước khi điều khiển.\n\n"
                "# Workflow\n1. Đọc state.\n2. Chỉ tắt khi chắc chắn không có người.\n\n"
                "# Safety rules\nKhông action khi sensor unavailable.",
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        settings.skills_dir = self.old_builtin
        settings.user_skills_dir = self.old_user
        self.tmp.cleanup()

    async def test_dry_run_executes_reads_but_suppresses_allowed_action(self):
        runtime = _Runtime()
        agent = Agent.__new__(Agent)
        agent.runtime = runtime
        agent.system_prompt = "You are HassMind."
        agent.client = _Client([
            _Response(tool_calls=[_ToolCall("r1", "ha_search_states", {"query": "test room", "domains": ["light"]})]),
            _Response(tool_calls=[_ToolCall("a1", "ha_call_service", {
                "domain": "light", "service": "turn_off", "target": {"entity_id": "light.test_room"}, "data": {}
            })]),
            _Response(content="Dry run: đèn đang bật; dự kiến tắt nhưng chưa thực thi."),
        ])
        schemas = [
            {"type": "function", "function": {"name": "ha_search_states", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "ha_call_service", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "skill_list", "parameters": {"type": "object", "properties": {}}}},
        ]
        with patch("app.agent.schemas", return_value=schemas):
            result = await agent.dry_run_skill(
                "presence-aware-control",
                "Kiểm tra light.test_room; nếu không có người thì tắt đèn.",
            )

        self.assertEqual([name for name, _ in runtime.calls], ["ha_search_states"])
        self.assertEqual(result["execution"]["actions_executed"], 0)
        self.assertEqual(result["execution"]["read_tools_executed"], 1)
        self.assertEqual(result["policy"]["status"], "allowed")
        self.assertEqual(result["planned_actions"][0]["tool"], "ha_call_service")
        self.assertEqual(result["planned_actions"][0]["summary"], "light.turn_off -> light.test_room")
        self.assertIn("ha_search_states", result["expected_tools"])
        self.assertIn("ha_call_service", result["expected_tools"])
        self.assertNotIn("skill_list", result["expected_tools"])
        self.assertIn("chưa thực thi", result["response_preview"])

    async def test_dry_run_reports_policy_block_without_executing_action(self):
        runtime = _Runtime()
        agent = Agent.__new__(Agent)
        agent.runtime = runtime
        agent.system_prompt = "You are HassMind."
        agent.client = _Client([
            _Response(tool_calls=[_ToolCall("a1", "ha_call_service", {
                "domain": "lock", "service": "unlock", "target": {"entity_id": "lock.front_door"}, "data": {}
            })]),
            _Response(content="Dry run: thao tác mở khóa bị policy chặn và không được thực thi."),
        ])
        schemas = [{"type": "function", "function": {"name": "ha_call_service", "parameters": {"type": "object", "properties": {}}}}]
        with patch("app.agent.schemas", return_value=schemas):
            result = await agent.dry_run_skill(
                "presence-aware-control",
                "Mở lock.front_door khi tôi về nhà.",
            )

        self.assertEqual(runtime.calls, [])
        self.assertEqual(result["execution"]["actions_executed"], 0)
        self.assertEqual(result["policy"]["status"], "blocked")
        self.assertEqual(result["planned_actions"][0]["policy"]["status"], "blocked")
        self.assertIn("blocked", result["planned_actions"][0]["policy"]["reason"].lower())

    async def test_dry_run_suppresses_custom_read_mode_when_http_method_is_not_get(self):
        runtime = _Runtime()
        tool_name = "ci_demo_refresh_deadbeef"
        runtime.integrations.custom_tools[tool_name] = (
            "demo",
            {"id": "refresh", "mode": "read", "method": "POST", "enabled": True, "agent_enabled": True},
        )
        agent = Agent.__new__(Agent)
        agent.runtime = runtime
        agent.system_prompt = "You are HassMind."
        agent.client = _Client([
            _Response(tool_calls=[_ToolCall("c1", tool_name, {"entity_id": "sensor.demo"})]),
            _Response(content="Dry run: custom POST bị giữ lại và không thực thi."),
        ])
        schemas = [{"type": "function", "function": {"name": tool_name, "parameters": {"type": "object", "properties": {}}}}]
        with patch("app.agent.schemas", return_value=schemas):
            result = await agent.dry_run_skill(
                "presence-aware-control",
                "Kiểm tra custom integration nhưng không được thay đổi gì.",
            )

        self.assertEqual(runtime.calls, [])
        self.assertEqual(result["execution"]["actions_executed"], 0)
        self.assertEqual(result["execution"]["read_tools_executed"], 0)
        self.assertEqual(result["policy"]["status"], "conditional")
        self.assertEqual(result["planned_actions"][0]["tool"], tool_name)
        self.assertIn("uses POST", result["planned_actions"][0]["policy"]["reason"])


if __name__ == "__main__":
    unittest.main()
