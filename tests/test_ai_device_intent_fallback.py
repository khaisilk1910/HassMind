"""Logic-first uncertain natural-language intents: AI classifies, HA supplies facts."""
import asyncio
import pytest

from app.logic_engine import LogicEngine, LogicFirstOrchestrator
from app.settings import settings
from test_device_status_report import _pump, _seed, device_setup
from test_logic_first_engine import FakeHA, FakeRuntime


class IntentAI:
    def __init__(self, response=None, error=None):
        self.response = response or {"intent": "device_status", "device_id": "pump-id", "confidence": 0.96}
        self.error = error
        self.classifications = []
        self.full_calls = []

    async def interpret_device_status(self, text, candidates):
        self.classifications.append((text, candidates))
        if self.error:
            raise self.error
        return self.response

    async def chat_with_trace(self, session_id, text, source="web"):
        self.full_calls.append((session_id, text, source))
        return {"text": "handled by standard AI", "tools": [], "engine": "ai"}


def setup_router(path, ai, *, second=None):
    devices = [_pump()] + ([second] if second else [])
    _seed(path, devices)
    ha = FakeHA([
        {"entity_id": "switch.oc1", "state": "on", "attributes": {"friendly_name": "Pump"}},
        {"entity_id": "sensor.oc1_power", "state": "10", "attributes": {"friendly_name": "Power", "unit_of_measurement": "W"}},
    ], devices=[{"id": "pump-id", "name": "Pump"}, {"id": "other-id", "name": "Other"}], entities=[
        {"device_id": "pump-id", "entity_id": "switch.oc1"},
        {"device_id": "pump-id", "entity_id": "sensor.oc1_power"},
    ])
    runtime = FakeRuntime(ha)
    return LogicFirstOrchestrator(ai, LogicEngine(runtime)), ha, runtime


@pytest.mark.asyncio
async def test_uncertain_colloquial_device_question_uses_ai_for_intent_and_logic_for_states(device_setup):
    ai = IntentAI()
    router, ha, runtime = setup_router(device_setup, ai)
    result = await router.chat_with_trace("c1", "\u1ed5 c\u1eafm b\u01a1m nh\u01b0 n\u00e0o", "web")
    assert result["reason"] == "ai_interpreted_device_status"
    assert result["engine"] == "ai+logic"
    assert "switch.oc1" in result["text"] and "10 W" in result["text"]
    assert len(ai.classifications) == 1 and len(ai.full_calls) == 0
    assert ai.classifications[0][1] == [{"device_id": "pump-id", "name": "\u1ed4 c\u1eafm B\u01a1m N\u01b0\u1edbc", "area": "B\u1ebfp"}]
    assert ha.state_calls == 1
    assert runtime.calls == []
    assert all(t["read_only"] and not t["side_effect"] for t in result["tools"])


@pytest.mark.asyncio
async def test_existing_explicit_device_status_does_not_call_ai(device_setup):
    ai = IntentAI()
    router, ha, _ = setup_router(device_setup, ai)
    result = await router.chat_with_trace("c2", "xem tr\u1ea1ng th\u00e1i \u1ed5 c\u1eafm b\u01a1m n\u01b0\u1edbc", "web")
    assert result["engine"] == "logic"
    assert not ai.classifications and not ai.full_calls
    assert ha.state_calls == 1


@pytest.mark.asyncio
async def test_ai_cannot_create_or_choose_unapproved_device(device_setup):
    ai = IntentAI(response={"intent": "device_status", "device_id": "attacker-id", "confidence": 0.99})
    router, ha, _ = setup_router(device_setup, ai)
    result = await router.chat_with_trace("c3", "\u1ed5 c\u1eafm b\u01a1m nh\u01b0 n\u00e0o", "web")
    assert result["reason"] == "ai_intent_needs_clarification"
    assert ha.state_calls == 0
    assert ai.full_calls == []


@pytest.mark.asyncio
async def test_ai_low_confidence_asks_not_guesses(device_setup):
    ai = IntentAI(response={"intent": "device_status", "device_id": "pump-id", "confidence": 0.70})
    router, ha, _ = setup_router(device_setup, ai)
    result = await router.chat_with_trace("c4", "b\u01a1m n\u01b0\u1edbc nh\u01b0 n\u00e0o", "web")
    assert result["reason"] == "ai_intent_needs_clarification"
    assert ha.state_calls == 0


@pytest.mark.asyncio
async def test_ai_other_intent_uses_full_agent_instead_of_reporting_states(device_setup):
    ai = IntentAI(response={"intent": "other", "device_id": "", "confidence": 0.97})
    router, ha, _ = setup_router(device_setup, ai)
    result = await router.chat_with_trace("c5", "\u1ed5 c\u1eafm b\u01a1m l\u00e0m th\u1ebf n\u00e0o", "web")
    assert result["text"] == "handled by standard AI"
    assert ai.full_calls and ha.state_calls == 0


@pytest.mark.asyncio
async def test_ai_intent_service_failure_returns_fast_recovery_instead_of_retry(device_setup):
    ai = IntentAI(error=asyncio.TimeoutError())
    router, ha, _ = setup_router(device_setup, ai)
    result = await router.chat_with_trace("c6", "\u1ed5 c\u1eafm b\u01a1m nh\u01b0 n\u00e0o", "web")
    assert result["reason"] == "ai_intent_unavailable"
    assert "AI" in result["text"]
    assert not ai.full_calls and ha.state_calls == 0


@pytest.mark.asyncio
async def test_ambiguous_device_query_asks_instead_of_picking_by_ai(device_setup):
    other = {"key": "backup", "name": "\u1ed4 c\u1eafm B\u01a1m N\u01b0\u1edbc 2",
             "aliases": ["b\u01a1m n\u01b0\u1edbc"], "match": {"device_id": "other-id"},
             "entities": {"mode": "auto"}}
    ai = IntentAI()
    router, ha, _ = setup_router(device_setup, ai, second=other)
    result = await router.chat_with_trace("c7", "b\u01a1m n\u01b0\u1edbc nh\u01b0 n\u00e0o?", "web")
    assert result["reason"] == "ambiguous_device"
    assert not ai.classifications and not ai.full_calls and ha.state_calls == 0


@pytest.mark.asyncio
async def test_commands_are_not_reinterpreted_as_read_only_reports(device_setup):
    ai = IntentAI()
    router, ha, runtime = setup_router(device_setup, ai)
    await router.chat_with_trace("c8", "t\u1eaft \u1ed5 c\u1eafm b\u01a1m n\u01b0\u1edbc", "web")
    assert not ai.classifications
    assert not any(tool == "ai_device_intent" for tool, _ in runtime.calls)


@pytest.mark.asyncio
async def test_web_fallback_agent_timeout_gives_structured_response(device_setup, monkeypatch):
    class SlowAI(IntentAI):
        async def chat_with_trace(self, *args, **kwargs):
            await asyncio.sleep(0.3)
    ai = SlowAI()
    router, _, _ = setup_router(device_setup, ai)
    monkeypatch.setattr(settings, "logic_ai_chat_timeout_seconds", 0.01)
    result = await router.chat_with_trace("c9", "explain an unknown event", "web")
    assert result["reason"] == "ai_agent_timeout"
    assert "AI" in result["text"]


@pytest.mark.asyncio
async def test_ai_intent_feature_flag_turns_off_classification(device_setup, monkeypatch):
    ai = IntentAI()
    router, _, _ = setup_router(device_setup, ai)
    monkeypatch.setattr(settings, "logic_ai_intent_enabled", False)
    result = await router.chat_with_trace("c10", "\u1ed5 c\u1eafm b\u01a1m nh\u01b0 n\u00e0o", "web")
    assert result["text"] == "handled by standard AI"
    assert ai.classifications == [] and ai.full_calls


@pytest.mark.asyncio
async def test_permission_or_howto_question_is_not_device_state_report(device_setup):
    ai = IntentAI()
    router, ha, _ = setup_router(device_setup, ai)
    result = await router.chat_with_trace(
        "c11", "c\u00f3 th\u1ec3 t\u1eaft \u1ed5 c\u1eafm b\u01a1m n\u01b0\u1edbc kh\u00f4ng?", "web")
    assert result["text"] == "handled by standard AI"
    assert ha.state_calls == 0
    assert ai.classifications == []
