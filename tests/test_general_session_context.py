"""All-topic session context: recall, isolation, bounded prompts and safe routing."""
import json
from types import SimpleNamespace

import pytest

from app.conversation_history import context_for_agent, is_contextual_followup
from app.db import add_message, get_messages, init_db
from app.logic_engine import LogicEngine, LogicFirstOrchestrator
from app.settings import settings
from test_logic_first_engine import FakeHA, FakeRuntime


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "history.db"))
    monkeypatch.setattr(settings, "conversation_context_max_chars", 12000)
    monkeypatch.setattr(settings, "conversation_recall_max_chars", 4500)
    monkeypatch.setattr(settings, "conversation_recall_exchanges", 4)
    init_db()
    return tmp_path


def test_general_topics_and_relevant_older_turns(database):
    sid = "chat-hass"
    add_message(sid, "user", "Tạo Scheduler kiểm tra trạng thái máy bơm", "web")
    add_message(sid, "assistant", "Scheduler cần tần suất kiểm tra phù hợp", "web")
    for i in range(25):
        add_message(sid, "user", f"Đây là câu hỏi độc lập thứ {i} về văn học", "web")
        add_message(sid, "assistant", f"Trả lời thứ {i}", "web")
    question = "Quay lại Scheduler máy bơm, tần suất nên thế nào?"
    add_message(sid, "user", question, "web")
    recent, recall_json = context_for_agent(sid, "web", question, 8)
    assert recent[-1]["content"] == question
    assert "Tạo Scheduler kiểm tra trạng thái máy bơm" not in str(recent)
    recall = json.loads(recall_json)
    assert any("Tạo Scheduler" in row["content"] for row in recall)
    assert any("tần suất" in row["content"] for row in recall)



def test_older_recall_scans_recent_rows_dropped_by_char_budget(database, monkeypatch):
    monkeypatch.setattr(settings, "conversation_context_max_chars", 2000)
    add_message("huge", "user", "Bàn về lịch bảo dưỡng máy lọc", "web")
    add_message("huge", "assistant", "Lịch bảo dưỡng mỗi tháng", "web")
    for i in range(6):
        add_message("huge", "user", "Viết chi tiết thật dài", "web")
        add_message("huge", "assistant", "x" * 14000, "web")
    question = "Quay lại lịch bảo dưỡng máy lọc?"
    add_message("huge", "user", question, "web")
    recent, recall = context_for_agent("huge", "web", question, 24)
    assert any("lịch bảo dưỡng" in item["content"] for item in json.loads(recall))
    assert recent[-1]["content"] == question

def test_isolation_web_zalo_and_system(database):
    sid = "collision"
    add_message(sid, "user", "Mã dự án WEB_ONLY", "web")
    add_message(sid, "assistant", "WEB_REPLY", "web")
    add_message(sid, "user", "Mã riêng ZALO_ONLY", "zalo")
    add_message(sid, "assistant", "ZALO_REPLY", "zalo")
    assert len(get_messages(sid, 20, source="web")) == 2
    add_message(sid, "user", "Mã WEB hỏi tiếp?", "web")
    web, recalled = context_for_agent(sid, "web", "Mã WEB hỏi tiếp?", 10)
    assert "ZALO_ONLY" not in str(web) + recalled
    assert "ZALO_REPLY" not in str(web) + recalled
    zalo, recalled = context_for_agent(sid, "zalo", "Mã riêng?", 10)
    assert "WEB_ONLY" not in str(zalo) + recalled
    other, recalled = context_for_agent("another-session", "web", "Mã riêng?", 10)
    assert other == [] and recalled == ""
    system, recalled = context_for_agent(sid, "system", "Đánh giá mới", 10)
    assert system == [{"role": "user", "content": "Đánh giá mới"}] and recalled == ""


def test_context_bound_and_latest_request_intact(database, monkeypatch):
    monkeypatch.setattr(settings, "conversation_context_max_chars", 2000)
    for i in range(18):
        add_message("big", "user", "Yêu cầu thử nghiệm " + "A" * 700, "web")
        add_message("big", "assistant", "B" * 11000, "web")
    question = "Yêu cầu hiện tại " + "C" * 2200
    add_message("big", "user", question, "web")
    recent, _ = context_for_agent("big", "web", question, 20)
    assert recent[-1]["content"] == question
    assert sum(len(m["content"]) for m in recent[:-1]) <= 2100


def test_anaphora_for_arbitrary_subjects():
    for question in ("Viết lại phần đó", "Giải thích thêm", "Còn kế hoạch lúc nãy?",
                     "Quay lại vấn đề Scheduler", "Rút gọn câu trả lời", "Vậy nó thì sao?"):
        assert is_contextual_followup(question), question
    for question in ("Tạo Scheduler mới", "Hiện tại sensor.bom trạng thái?",
                     "Hôm nay trời thế nào?", "Bật light.bedroom"):
        assert not is_contextual_followup(question), question


class StubAgent:
    def __init__(self):
        self.calls = []
    async def chat_with_trace(self, sid, text, source="web"):
        self.calls.append((sid, text, source))
        return {"text": "AI dùng lịch sử", "tools": []}
    async def interpret_device_status(self, *args):
        return {"intent": "other", "device_id": "", "confidence": 0.0}


@pytest.mark.asyncio
async def test_general_followup_is_not_handled_as_new_ha_query(database):
    ai = StubAgent()
    ha = FakeHA([{"entity_id": "light.bedroom", "state": "on", "attributes": {"friendly_name": "Đèn phòng ngủ"}}])
    runtime = FakeRuntime(ha)
    router = LogicFirstOrchestrator(ai, LogicEngine(runtime))
    add_message("general", "user", "Viết hướng dẫn bật đèn phòng ngủ", "web")
    add_message("general", "assistant", "Tôi sẽ đưa quy trình thao tác", "web")
    result = await router.chat_with_trace("general", "Vậy nó đang bật hay tắt?", "web")
    # A missing verified Device focus must not become an automatic control action.
    assert result["engine"] == "ai"
    assert runtime.calls == []
    assert len(ai.calls) == 1
    assert result["reason"] == "session_general_followup"


@pytest.mark.asyncio
async def test_agent_receives_old_references_and_recent_for_general_topics(database, monkeypatch):
    # Isolate the agent prompt builder with dummy SDK modules; real service tests
    # still require the production openai/mcp dependencies in the deployed image.
    import sys
    import types
    import importlib
    if "openai" not in sys.modules:
        sdk = types.ModuleType("openai")
        sdk.AsyncOpenAI = object
        monkeypatch.setitem(sys.modules, "openai", sdk)
    if "mcp" not in sys.modules:
        sdk = types.ModuleType("mcp")
        sdk.ClientSession = object
        monkeypatch.setitem(sys.modules, "mcp", sdk)
        client_pkg = types.ModuleType("mcp.client")
        client_pkg.__path__ = []
        monkeypatch.setitem(sys.modules, "mcp.client", client_pkg)
        transport = types.ModuleType("mcp.client.streamable_http")
        transport.streamable_http_client = object
        monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", transport)
    agent_module = importlib.import_module("app.agent")
    Agent = agent_module.Agent
    captured = []
    async def completion_create(**kwargs):
        captured.append(kwargs["messages"])
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="Đã hiểu ngữ cảnh", tool_calls=None),
            finish_reason="stop")], usage=None)
    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=completion_create)))
    agent.system_prompt = "Base HassMind agent policy"
    agent.runtime = SimpleNamespace()
    monkeypatch.setattr(agent_module, "schemas", lambda: [])
    sid = "chat-complex"
    add_message(sid, "user", "Viết email xin báo giá máy bơm ABC", "web")
    add_message(sid, "assistant", "Email: Kính gửi phòng kinh doanh", "web")
    for i in range(15):
        add_message(sid, "user", f"Đổi sang bài toán toán học số {i}", "web")
        add_message(sid, "assistant", "Giải toán", "web")
    question = "Quay lại email máy bơm ABC, viết ngắn lại"
    answer = await agent.chat(sid, question, "web")
    assert answer == "Đã hiểu ngữ cảnh"
    content = "\n".join(str(item["content"]) for item in captured[-1])
    assert "Kính gửi phòng kinh doanh" in content
    assert question in content
    assert "MULTI-TURN SESSION CONTEXT" in content
    assert "not live evidence" in content
