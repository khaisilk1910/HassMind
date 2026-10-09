"""Multi-turn Logic-First routing cannot leak or hallucinate HA device context."""
import pytest
from app import conversation_context as context
from app import rag
from app.db import read_session_device_focus, save_session_device_focus, clear_session_device_focus
from app.logic_engine import LogicEngine, LogicFirstOrchestrator
from app.settings import settings
from test_device_status_report import _pump, _seed, device_setup
from test_logic_first_engine import FakeHA, FakeRuntime


class AIStub:
    def __init__(self):
        self.calls = []

    async def chat_with_trace(self, sid, text, source="web"):
        self.calls.append((sid, text, source))
        return {"text": "AI reply", "tools": []}

    async def interpret_device_status(self, *args):
        return {"intent": "other", "device_id": "", "confidence": 1.0}


def build_router(path, additional=None):
    _seed(path, [_pump(), *(additional or [])])
    ha = FakeHA([
        {"entity_id": "switch.oc1", "state": "on", "attributes": {"friendly_name": "Ổ cắm Bơm Nước"}},
        {"entity_id": "sensor.pump_power", "state": "10", "attributes": {"friendly_name": "Power", "unit_of_measurement": "W"}},
        {"entity_id": "sensor.pump_voltage", "state": "235", "attributes": {"friendly_name": "Voltage", "unit_of_measurement": "V"}},
        {"entity_id": "sensor.pump_current", "state": "0.1", "attributes": {"friendly_name": "Current", "unit_of_measurement": "A"}},
        {"entity_id": "sensor.other_power", "state": "999", "attributes": {"friendly_name": "Other power", "unit_of_measurement": "W"}},
    ], devices=[{"id": "pump-id"}], entities=[
        {"device_id": "pump-id", "entity_id": "switch.oc1"},
        {"device_id": "pump-id", "entity_id": "sensor.pump_power", "original_name": "Power"},
        {"device_id": "pump-id", "entity_id": "sensor.pump_voltage", "original_name": "Voltage"},
        {"device_id": "pump-id", "entity_id": "sensor.pump_current", "original_name": "Current"},
        {"device_id": "other-id", "entity_id": "sensor.other_power"},
    ])
    runtime=FakeRuntime(ha)
    ai=AIStub()
    return LogicFirstOrchestrator(ai,LogicEngine(runtime)), ha, runtime, ai


@pytest.mark.asyncio
async def test_followup_reads_current_state_and_only_selected_property(device_setup):
    router,ha,runtime,ai = build_router(device_setup)
    first = await router.chat_with_trace('user-1','xem trạng thái ổ cắm bơm nước','web')
    assert first['reason']=='device_state_report'
    assert read_session_device_focus('user-1','web')=='pump-id'
    ha._states['sensor.pump_voltage']['state']='238'
    next_turn=await router.chat_with_trace('user-1','còn điện áp thì sao?','web')
    assert next_turn['reason']=='session_device_followup'
    assert next_turn['engine']=='logic'
    assert '238 V' in next_turn['text']
    assert 'sensor.pump_power' not in next_turn['text']
    assert 'sensor.other_power' not in next_turn['text']
    assert not ai.calls and not runtime.calls
    assert ha.state_calls==2


@pytest.mark.asyncio
async def test_followup_pronoun_on_off_reads_switch_never_actuates(device_setup):
    router,ha,runtime,ai=build_router(device_setup)
    await router.chat_with_trace('s','xem ổ cắm bơm nước hiện tại','web')
    r=await router.chat_with_trace('s','nó đang bật hay tắt?','web')
    assert r['reason']=='session_device_followup'
    assert 'switch.oc1' in r['text']
    assert 'sensor.pump_power' not in r['text']
    assert runtime.calls==[] and ai.calls==[]


@pytest.mark.asyncio
async def test_context_is_isolated_per_session_and_transport(device_setup):
    router,ha,runtime,ai=build_router(device_setup)
    await router.chat_with_trace('s1','ổ cắm bơm nước trạng thái?','web')
    assert context.focused_device('s1','web') is not None
    assert context.focused_device('s2','web') is None
    assert context.focused_device('s1','zalo') is None
    no_focus=await router.chat_with_trace('s2','còn điện áp?','web')
    assert no_focus['text']=='AI reply' and no_focus['engine']=='ai'
    assert context.focused_device('s1','web') is not None


@pytest.mark.asyncio
async def test_new_topic_and_explicit_other_room_do_not_reuse_old_target(device_setup):
    router,ha,runtime,ai=build_router(device_setup)
    await router.chat_with_trace('s','xem trạng thái ổ cắm bơm nước','web')
    unrelated=await router.chat_with_trace('s','hôm nay thời tiết ra sao?','web')
    assert unrelated['text']=='AI reply'
    assert context.focused_device('s','web') is None
    after=await router.chat_with_trace('s','còn công suất?','web')
    assert after['engine']=='ai'


@pytest.mark.asyncio
async def test_followup_control_not_executed_by_context_router(device_setup):
    router,ha,runtime,ai=build_router(device_setup)
    await router.chat_with_trace('s','xem trạng thái ổ cắm bơm nước','web')
    r=await router.chat_with_trace('s','tắt nó đi','web')
    assert r['engine']=='ai' and ai.calls
    assert ha._states['switch.oc1']['state']=='on'
    assert runtime.calls==[]


@pytest.mark.asyncio
async def test_system_runs_have_no_chat_context(device_setup):
    router,ha,runtime,ai=build_router(device_setup)
    await router.chat_with_trace('job','ổ cắm bơm nước trạng thái?','system')
    assert context.focused_device('job','system') is None
    r=await router.chat_with_trace('job','còn điện áp?','system')
    assert r['engine']=='ai'


@pytest.mark.asyncio
async def test_device_removed_from_knowledge_clears_stale_focus(device_setup):
    router,ha,runtime,ai=build_router(device_setup)
    await router.chat_with_trace('s','xem trạng thái ổ cắm bơm nước','web')
    _seed(device_setup, [])
    assert context.focused_device('s','web') is None
    r=await router.chat_with_trace('s','còn điện áp?','web')
    assert r['engine']=='ai'


def test_context_ttl_and_reset_and_non_action_intents(device_setup,monkeypatch):
    build_router(device_setup)
    save_session_device_focus('x','web','pump-id')
    assert read_session_device_focus('x','web') == 'pump-id'
    monkeypatch.setattr(settings,'conversation_focus_minutes',1)
    import app.db as db
    with db.conn() as c:
        c.execute('UPDATE session_device_focus SET updated_at=updated_at-120 WHERE session_id=?',('x',))
    assert context.focused_device('x','web') is None
    clear_session_device_focus('x','web')
    assert read_session_device_focus('x','web')==''
    assert context.followup_read_request('còn điện áp?') == (True,'voltage')
    assert context.followup_read_request('vậy nó thế nào?') == (True,None)
    assert context.followup_read_request('thời tiết hôm nay ra sao?') == (False,None)
    assert context.followup_read_request('bật nó đi') == (False,None)

@pytest.mark.asyncio
async def test_two_overlapping_turns_same_session_are_serialized(device_setup):
    import asyncio
    router,ha,runtime,ai=build_router(device_setup)
    base=ha.states
    first_started=asyncio.Event()
    release_first=asyncio.Event()
    calls=0

    async def slow_states(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls == 1:
            first_started.set()
            await release_first.wait()
        return await base(*args,**kwargs)

    ha.states=slow_states
    first=asyncio.create_task(router.chat_with_trace('same','xem trạng thái ổ cắm bơm nước','web'))
    await asyncio.wait_for(first_started.wait(),timeout=2)
    second=asyncio.create_task(router.chat_with_trace('same','còn điện áp?','web'))
    await asyncio.sleep(0.01)
    assert calls==1  # second message queued until the first commits focus
    release_first.set()
    a,b=await asyncio.gather(first,second)
    assert a['reason']=='device_state_report'
    assert b['reason']=='session_device_followup'
    assert ai.calls==[]


@pytest.mark.asyncio
async def test_analytical_followup_defers_to_agent_without_ha_actuation(device_setup):
    router,ha,runtime,ai=build_router(device_setup)
    await router.chat_with_trace('s','xem trạng thái ổ cắm bơm nước','web')
    r=await router.chat_with_trace('s','tại sao điện áp nó lại thấp?','web')
    assert r['engine']=='ai' and ai.calls
    assert runtime.calls==[]

@pytest.mark.asyncio
async def test_explicit_new_device_replaces_old_focus(device_setup):
    second={"key":"air","name":"Máy lọc không khí","aliases":["máy lọc"],
            "match":{"device_id":"air-id"},"entities":{"mode":"auto"}}
    router,ha,runtime,ai=build_router(device_setup,[second])
    ha._devices.append({"id":"air-id"})
    ha._entities.append({"device_id":"air-id","entity_id":"sensor.air_power","original_name":"Power"})
    ha._states['sensor.air_power']={"entity_id":"sensor.air_power","state":"50","attributes":{"unit_of_measurement":"W"}}
    await router.chat_with_trace('s','xem trạng thái ổ cắm bơm nước','web')
    r=await router.chat_with_trace('s','trạng thái máy lọc không khí?','web')
    assert r['reason']=='device_state_report'
    assert context.focused_device('s','web')['device_id']=='air-id'
    followup=await router.chat_with_trace('s','còn công suất?','web')
    assert '50 W' in followup['text']
    assert 'sensor.pump_power' not in followup['text']
