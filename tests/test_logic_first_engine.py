import json
from pathlib import Path

import pytest

from app.db import init_db
from app.logic_engine import LogicEngine, LogicFirstOrchestrator
from app.notifications import NO_NOTIFY_TOKEN
from app.settings import settings


class FakeHA:
    def __init__(self, states, areas=None, entities=None, devices=None):
        self._states = {x["entity_id"]: dict(x) for x in states}
        self._areas = areas or []
        self._entities = entities or []
        self._devices = devices or []
        self.state_calls = 0

    async def states(self, fresh=False):
        self.state_calls += 1
        return [dict(v) for v in self._states.values()]

    async def area_registry(self):
        return list(self._areas)

    async def entity_registry(self):
        return list(self._entities)

    async def device_registry(self):
        return list(self._devices)


class FakeRuntime:
    def __init__(self, ha, fail=False):
        self.ha = ha
        self.fail = fail
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, args))
        if self.fail:
            raise RuntimeError("simulated failure")
        if name == "ha_call_service":
            domain = args["domain"]
            service = args["service"]
            data = args.get("data") or {}
            target = args.get("target") or {}
            ids = target.get("entity_id") or []
            if isinstance(ids, str):
                ids = [ids]
            for eid in ids:
                if eid not in self.ha._states:
                    continue
                item = self.ha._states[eid]
                attrs = item.setdefault("attributes", {})
                if service == "turn_off":
                    item["state"] = "off"
                elif service == "turn_on" and domain != "script":
                    item["state"] = "on"
                elif domain == "climate" and service == "set_hvac_mode":
                    item["state"] = data.get("hvac_mode", item.get("state"))
                elif domain == "climate" and service == "set_temperature":
                    attrs["temperature"] = data.get("temperature")
                elif domain == "fan" and service == "set_preset_mode":
                    attrs["preset_mode"] = data.get("preset_mode")
            return {"ok": True}
        raise AssertionError(name)


class FakeAI:
    def __init__(self):
        self.calls = 0

    async def chat_with_trace(self, session_id, text, source="web"):
        self.calls += 1
        return {"text": "AI fallback", "tools": []}


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "hassmind.db"))
    monkeypatch.setattr(settings, "logic_first_enabled", True)
    monkeypatch.setattr(settings, "logic_repeat_failure_limit", 2)
    monkeypatch.setattr(settings, "logic_repeat_failure_window_minutes", 30)
    init_db()
    return tmp_path


@pytest.mark.asyncio
async def test_exact_state_query_uses_logic_without_ai(isolated_db):
    ha = FakeHA([
        {"entity_id": "sensor.room_temperature", "state": "28.5", "attributes": {"friendly_name": "Nhiệt độ phòng", "unit_of_measurement": "°C"}},
    ])
    logic = LogicEngine(FakeRuntime(ha))
    ai = FakeAI()
    router = LogicFirstOrchestrator(ai, logic)

    result = await router.chat_with_trace("s1", "Trạng thái sensor.room_temperature hiện tại?", "web")

    assert result["engine"] == "logic"
    assert "28.5 °C" in result["text"]
    assert ai.calls == 0
    assert result["tools"][0]["tool"] == "ha_get_states"


@pytest.mark.asyncio
async def test_exact_direct_control_is_verified_by_code(isolated_db):
    ha = FakeHA([
        {"entity_id": "light.bedroom", "state": "on", "attributes": {"friendly_name": "Đèn phòng ngủ"}},
    ])
    runtime = FakeRuntime(ha)
    logic = LogicEngine(runtime)

    result = await logic.try_handle("Tắt light.bedroom", source="web")

    assert result.handled is True
    assert "Đã tắt" in result.text
    assert ha._states["light.bedroom"]["state"] == "off"
    assert any(x.get("side_effect") and x.get("status") == "ok" for x in result.trace)


@pytest.mark.asyncio
async def test_complex_conditional_request_falls_back_to_ai(isolated_db):
    ha = FakeHA([
        {"entity_id": "light.bedroom", "state": "on", "attributes": {}},
        {"entity_id": "binary_sensor.pn_status", "state": "off", "attributes": {}},
    ])
    logic = LogicEngine(FakeRuntime(ha))
    result = await logic.try_handle(
        "Nếu binary_sensor.pn_status off thì tắt light.bedroom, nhưng chỉ khi không có người",
        source="web",
    )
    assert result.handled is False
    assert result.reason == "semantic_or_complex"


@pytest.mark.asyncio
async def test_vacancy_profile_turns_off_only_verified_safe_area(isolated_db, tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "job3.json").write_text(json.dumps({
        "name": "job3",
        "recipe": "vacancy_shutdown",
        "areas": [
            {"name": "Phòng khách", "presence": "binary_sensor.pk_status", "tv": ["media_player.pk_tv"]},
            {"name": "Phòng ngủ", "presence": "binary_sensor.pn_status", "tv": []},
        ],
        "domains": ["light", "fan", "switch"],
        "switch_allowlist": ["switch.bedroom_fan_power"],
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "logic_profiles_dir", str(profiles))
    monkeypatch.setattr(settings, "user_logic_profiles_dir", str(tmp_path / "user-profiles"))

    states = [
        {"entity_id": "binary_sensor.pk_status", "state": "off", "attributes": {}},
        {"entity_id": "media_player.pk_tv", "state": "off", "attributes": {}},
        {"entity_id": "binary_sensor.pn_status", "state": "on", "attributes": {}},
        {"entity_id": "light.pk_ceiling", "state": "on", "attributes": {"friendly_name": "Đèn trần"}},
        {"entity_id": "light.bedroom", "state": "on", "attributes": {"friendly_name": "Đèn ngủ"}},
        {"entity_id": "switch.unknown_load", "state": "on", "attributes": {"friendly_name": "Công tắc lạ"}},
    ]
    areas = [{"area_id": "pk", "name": "Phòng khách"}, {"area_id": "pn", "name": "Phòng ngủ"}]
    entities = [
        {"entity_id": "light.pk_ceiling", "area_id": "pk", "device_id": None},
        {"entity_id": "light.bedroom", "area_id": "pn", "device_id": None},
        {"entity_id": "switch.unknown_load", "area_id": "pk", "device_id": None},
    ]
    ha = FakeHA(states, areas=areas, entities=entities)
    runtime = FakeRuntime(ha)
    logic = LogicEngine(runtime)

    result = await logic.try_handle("@logic-profile job3", source="system")

    assert result.handled is True
    assert "Phòng khách" in result.text
    assert "Đèn trần" in result.text
    assert ha._states["light.pk_ceiling"]["state"] == "off"
    assert ha._states["light.bedroom"]["state"] == "on"  # presence on
    assert ha._states["switch.unknown_load"]["state"] == "on"  # not allowlisted
    assert any(x.get("side_effect") and x.get("status") == "ok" for x in result.trace)


@pytest.mark.asyncio
async def test_vacancy_profile_is_silent_when_tv_active(isolated_db, tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "job3.json").write_text(json.dumps({
        "recipe": "vacancy_shutdown",
        "areas": [{"name": "Phòng khách", "presence": "binary_sensor.pk_status", "tv": ["media_player.pk_tv"]}],
        "domains": ["light"],
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "logic_profiles_dir", str(profiles))
    monkeypatch.setattr(settings, "user_logic_profiles_dir", str(tmp_path / "user-profiles"))

    ha = FakeHA([
        {"entity_id": "binary_sensor.pk_status", "state": "off", "attributes": {}},
        {"entity_id": "media_player.pk_tv", "state": "playing", "attributes": {}},
        {"entity_id": "light.pk_ceiling", "state": "on", "attributes": {}},
    ], areas=[{"area_id": "pk", "name": "Phòng khách"}], entities=[{"entity_id": "light.pk_ceiling", "area_id": "pk"}])
    runtime = FakeRuntime(ha)
    result = await LogicEngine(runtime).try_handle("@logic-profile job3", source="system")

    assert result.text == NO_NOTIFY_TOKEN
    assert runtime.calls == []
    assert ha._states["light.pk_ceiling"]["state"] == "on"

@pytest.mark.asyncio
async def test_event_context_does_not_pollute_exact_action_targets(isolated_db):
    ha = FakeHA([
        {"entity_id": "binary_sensor.door", "state": "on", "attributes": {}},
        {"entity_id": "light.hall", "state": "on", "attributes": {"friendly_name": "Đèn hành lang"}},
    ])
    runtime = FakeRuntime(ha)
    logic = LogicEngine(runtime)
    text = "Tắt light.hall\n\nEvent context: entity_id=binary_sensor.door, new_state=on, attributes={}"

    result = await logic.try_handle(text, source="system")

    assert result.handled is True
    assert ha._states["light.hall"]["state"] == "off"
    assert ha._states["binary_sensor.door"]["state"] == "on"
    called_ids = runtime.calls[0][1]["target"]["entity_id"]
    assert called_ids == ["light.hall"]

@pytest.mark.asyncio
async def test_legacy_job3_prompt_auto_routes_to_logic_profile(isolated_db, tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "job3-vacancy-shutdown.json").write_text(json.dumps({
        "recipe": "vacancy_shutdown",
        "areas": [{"name": "Phòng khách", "presence": "binary_sensor.pk_status", "tv": ["remote.box_phong_khach", "media_player.box_phong_khach_2"]}],
        "domains": ["light"],
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "logic_profiles_dir", str(profiles))
    monkeypatch.setattr(settings, "user_logic_profiles_dir", str(tmp_path / "user-profiles"))

    ha = FakeHA([
        {"entity_id": "binary_sensor.pk_status", "state": "off", "attributes": {}},
        {"entity_id": "remote.box_phong_khach", "state": "off", "attributes": {}},
        {"entity_id": "media_player.box_phong_khach_2", "state": "off", "attributes": {}},
        {"entity_id": "light.pk_ceiling", "state": "on", "attributes": {"friendly_name": "Đèn trần"}},
    ], areas=[{"area_id": "pk", "name": "Phòng khách"}], entities=[{"entity_id": "light.pk_ceiling", "area_id": "pk"}])
    runtime = FakeRuntime(ha)
    logic = LogicEngine(runtime)
    prompt = """Kiểm tra đèn, quạt đang bật và tắt khi không có hiện diện. Tivi gồm:
media_player.xiaomi_tv_box_2, remote.xiaomi_tv_box, remote.box_phong_bep,
media_player.box_phong_bep_2, remote.box_phong_khach, media_player.box_phong_khach_2."""

    result = await logic.try_handle(prompt, source="system")

    assert result.handled is True
    assert result.reason == "legacy_job3_auto_profile"
    assert ha._states["light.pk_ceiling"]["state"] == "off"

@pytest.mark.asyncio
async def test_unique_friendly_name_state_query_uses_logic_without_ai(isolated_db):
    ha = FakeHA([
        {"entity_id": "sensor.bedroom_temperature", "state": "27.2", "attributes": {"friendly_name": "Nhiệt độ phòng ngủ", "unit_of_measurement": "°C"}},
    ])
    ai = FakeAI()
    router = LogicFirstOrchestrator(ai, LogicEngine(FakeRuntime(ha)))

    result = await router.chat_with_trace("s-friendly", "Nhiệt độ phòng ngủ hiện tại?", "web")

    assert result["engine"] == "logic"
    assert "27.2 °C" in result["text"]
    assert ai.calls == 0


@pytest.mark.asyncio
async def test_ambiguous_friendly_name_asks_user_instead_of_guessing(isolated_db):
    ha = FakeHA([
        {"entity_id": "light.bedroom_a", "state": "on", "attributes": {"friendly_name": "Đèn phòng ngủ"}},
        {"entity_id": "switch.bedroom_a", "state": "on", "attributes": {"friendly_name": "Đèn phòng ngủ"}},
    ])
    runtime = FakeRuntime(ha)
    result = await LogicEngine(runtime).try_handle("Tắt Đèn phòng ngủ", source="web")

    assert result.handled is True
    assert result.reason == "ambiguous_friendly_name"
    assert "Hãy chọn đúng entity" in result.text
    assert "light.bedroom_a" in result.text
    assert "switch.bedroom_a" in result.text
    assert runtime.calls == []

@pytest.mark.asyncio
async def test_repeated_exact_failure_is_remembered_and_next_retry_requires_confirmation(isolated_db):
    ha = FakeHA([
        {"entity_id": "light.problem", "state": "on", "attributes": {"friendly_name": "Đèn lỗi"}},
    ])
    runtime = FakeRuntime(ha, fail=True)
    logic = LogicEngine(runtime)

    first = await logic.try_handle("Tắt light.problem", source="web")
    second = await logic.try_handle("Tắt light.problem", source="web")
    third = await logic.try_handle("Tắt light.problem", source="web")

    assert first.handled is True
    assert second.handled is True
    assert "thử lại" in third.text.lower()
    assert third.reason == "repeated_failure_clarification"
    assert len(runtime.calls) == 2

@pytest.mark.asyncio
async def test_bedroom_climate_profile_uses_fixed_27c_and_fan_for_hot_room(isolated_db, tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile = json.loads(Path("config/logic_profiles/bedroom-climate-comfort.json").read_text(encoding="utf-8"))
    # Keep one room so the assertion stays focused.
    profile["rooms"] = [profile["rooms"][0]]
    (profiles / "bedroom-climate-comfort.json").write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(settings, "logic_profiles_dir", str(profiles))
    monkeypatch.setattr(settings, "user_logic_profiles_dir", str(tmp_path / "user-profiles"))

    states = [
        {"entity_id": "sensor.xiaomi_m9_daa3_temperature", "state": "31.0", "attributes": {}},
        {"entity_id": "sensor.xiaomi_m9_daa3_relative_humidity", "state": "78", "attributes": {}},
        {"entity_id": "binary_sensor.pn_status", "state": "on", "attributes": {}},
        {"entity_id": "climate.xiaomi_m9_daa3_air_conditioner", "state": "off", "attributes": {"temperature": 25, "hvac_modes": ["off", "cool", "dry"]}},
        {"entity_id": "switch.ct3_ngoai_pn_kn_left", "state": "off", "attributes": {}},
    ]
    for speed in range(1, 7):
        states.append({"entity_id": f"script.fan_light_pn_kn_fan_{speed}", "state": "off", "attributes": {}})
    ha = FakeHA(states)
    runtime = FakeRuntime(ha)

    result = await LogicEngine(runtime).try_handle("@logic-profile bedroom-climate-comfort", source="system")

    assert result.handled is True
    assert result.reason == "climate_verified_actions"
    climate = ha._states["climate.xiaomi_m9_daa3_air_conditioner"]
    assert climate["state"] == "cool"
    assert climate["attributes"]["temperature"] == 27
    assert ha._states["switch.ct3_ngoai_pn_kn_left"]["state"] == "on"
    service_calls = [args for name, args in runtime.calls if name == "ha_call_service"]
    assert any(x["domain"] == "script" and x["target"]["entity_id"] == "script.fan_light_pn_kn_fan_6" for x in service_calls)
    assert not any((x.get("data") or {}).get("temperature") in {25, 26} for x in service_calls)
    assert "27°C" in result.text


@pytest.mark.asyncio
async def test_bedroom_climate_profile_is_silent_without_action(isolated_db, tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile = json.loads(Path("config/logic_profiles/bedroom-climate-comfort.json").read_text(encoding="utf-8"))
    profile["rooms"] = [profile["rooms"][1]]
    (profiles / "bedroom-climate-comfort.json").write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(settings, "logic_profiles_dir", str(profiles))
    monkeypatch.setattr(settings, "user_logic_profiles_dir", str(tmp_path / "user-profiles"))

    ha = FakeHA([
        {"entity_id": "sensor.xiaomi_m15_1480_temperature", "state": "25.5", "attributes": {}},
        {"entity_id": "sensor.xiaomi_m15_1480_relative_humidity", "state": "50", "attributes": {}},
        {"entity_id": "binary_sensor.ph_status", "state": "off", "attributes": {}},
        {"entity_id": "climate.xiaomi_m15_1480_air_conditioner", "state": "off", "attributes": {"temperature": 27, "hvac_modes": ["off", "cool"]}},
        {"entity_id": "switch.ct4_phong_soc_chip_l3", "state": "off", "attributes": {}},
        {"entity_id": "fan.sonoff_1000a827dd", "state": "off", "attributes": {"preset_mode": "off", "preset_modes": ["off", "low", "medium", "high"]}},
    ])
    runtime = FakeRuntime(ha)
    result = await LogicEngine(runtime).try_handle("@logic-profile bedroom-climate-comfort", source="system")

    assert result.text == NO_NOTIFY_TOKEN
    assert runtime.calls == []

@pytest.mark.asyncio
async def test_legacy_bedroom_skill_scheduler_prompt_auto_routes_to_logic_profile(isolated_db, tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile = json.loads(Path("config/logic_profiles/bedroom-climate-comfort.json").read_text(encoding="utf-8"))
    profile["rooms"] = [profile["rooms"][1]]
    (profiles / "bedroom-climate-comfort.json").write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(settings, "logic_profiles_dir", str(profiles))
    monkeypatch.setattr(settings, "user_logic_profiles_dir", str(tmp_path / "user-profiles"))
    ha = FakeHA([
        {"entity_id": "sensor.xiaomi_m15_1480_temperature", "state": "25.0", "attributes": {}},
        {"entity_id": "sensor.xiaomi_m15_1480_relative_humidity", "state": "50", "attributes": {}},
        {"entity_id": "binary_sensor.ph_status", "state": "off", "attributes": {}},
        {"entity_id": "climate.xiaomi_m15_1480_air_conditioner", "state": "off", "attributes": {"temperature": 27, "hvac_modes": ["off", "cool"]}},
        {"entity_id": "switch.ct4_phong_soc_chip_l3", "state": "off", "attributes": {}},
        {"entity_id": "fan.sonoff_1000a827dd", "state": "off", "attributes": {"preset_mode": "off", "preset_modes": ["off", "low", "medium", "high"]}},
    ])
    result = await LogicEngine(FakeRuntime(ha)).try_handle(
        "Dùng skill bedroom-climate-comfort kiểm tra Phòng ngủ và Phòng Sóc Chíp.",
        source="system",
    )
    assert result.handled is True
    assert result.reason == "legacy_bedroom_climate_auto_profile"
    assert result.text == NO_NOTIFY_TOKEN

@pytest.mark.asyncio
async def test_room_status_phrase_uses_fixed_profile_mapping_without_ai(isolated_db, tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    climate_profile = json.loads(Path("config/logic_profiles/bedroom-climate-comfort.json").read_text(encoding="utf-8"))
    vacancy_profile = json.loads(Path("config/logic_profiles/job3-vacancy-shutdown.json").read_text(encoding="utf-8"))
    (profiles / "bedroom-climate-comfort.json").write_text(json.dumps(climate_profile), encoding="utf-8")
    (profiles / "job3-vacancy-shutdown.json").write_text(json.dumps(vacancy_profile), encoding="utf-8")
    monkeypatch.setattr(settings, "logic_profiles_dir", str(profiles))
    monkeypatch.setattr(settings, "user_logic_profiles_dir", str(tmp_path / "user-profiles"))

    ha = FakeHA([
        {"entity_id": "sensor.xiaomi_m9_daa3_temperature", "state": "28.1", "attributes": {"unit_of_measurement": "°C"}},
        {"entity_id": "sensor.xiaomi_m9_daa3_relative_humidity", "state": "62", "attributes": {"unit_of_measurement": "%"}},
        {"entity_id": "binary_sensor.pn_status", "state": "on", "attributes": {}},
        {"entity_id": "climate.xiaomi_m9_daa3_air_conditioner", "state": "off", "attributes": {"temperature": 25, "hvac_action": "off"}},
        {"entity_id": "switch.ct3_ngoai_pn_kn_left", "state": "on", "attributes": {}},
        {"entity_id": "media_player.xiaomi_tv_box_2", "state": "off", "attributes": {}},
        {"entity_id": "remote.xiaomi_tv_box", "state": "off", "attributes": {}},
    ])
    ai = FakeAI()
    router = LogicFirstOrchestrator(ai, LogicEngine(FakeRuntime(ha)))

    result = await router.chat_with_trace("room-status", "xem trạng thái phòng ngủ", "web")

    assert result["engine"] == "logic"
    assert result["reason"] == "mapped_room_status"
    assert "28.1°C" in result["text"]
    assert "Điều hòa:** off" in result["text"]
    assert "target 25" not in result["text"]  # stored target must not imply AC is on
    assert ai.calls == 0


@pytest.mark.asyncio
async def test_explicit_bedroom_skill_in_web_chat_routes_to_logic_profile(isolated_db, tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile = json.loads(Path("config/logic_profiles/bedroom-climate-comfort.json").read_text(encoding="utf-8"))
    profile["rooms"] = [profile["rooms"][1]]
    (profiles / "bedroom-climate-comfort.json").write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(settings, "logic_profiles_dir", str(profiles))
    monkeypatch.setattr(settings, "user_logic_profiles_dir", str(tmp_path / "user-profiles"))

    ha = FakeHA([
        {"entity_id": "sensor.xiaomi_m15_1480_temperature", "state": "25.0", "attributes": {}},
        {"entity_id": "sensor.xiaomi_m15_1480_relative_humidity", "state": "50", "attributes": {}},
        {"entity_id": "binary_sensor.ph_status", "state": "off", "attributes": {}},
        {"entity_id": "climate.xiaomi_m15_1480_air_conditioner", "state": "off", "attributes": {"temperature": 27, "hvac_modes": ["off", "cool"]}},
        {"entity_id": "switch.ct4_phong_soc_chip_l3", "state": "off", "attributes": {}},
        {"entity_id": "fan.sonoff_1000a827dd", "state": "off", "attributes": {"preset_mode": "off", "preset_modes": ["off", "low", "medium", "high"]}},
    ])
    ai = FakeAI()
    result = await LogicFirstOrchestrator(ai, LogicEngine(FakeRuntime(ha))).chat_with_trace(
        "skill-web",
        "Hãy dùng skill bedroom-climate-comfort kiểm tra Phòng ngủ và Phòng Sóc Chíp.",
        "web",
    )
    assert result["engine"] == "logic"
    assert result["reason"] == "legacy_bedroom_climate_auto_profile"
    assert ai.calls == 0


@pytest.mark.asyncio
async def test_logic_profile_dry_run_reads_and_plans_without_mutation(isolated_db, tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile = json.loads(Path("config/logic_profiles/bedroom-climate-comfort.json").read_text(encoding="utf-8"))
    profile["rooms"] = [profile["rooms"][0]]
    (profiles / "bedroom-climate-comfort.json").write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(settings, "logic_profiles_dir", str(profiles))
    monkeypatch.setattr(settings, "user_logic_profiles_dir", str(tmp_path / "user-profiles"))

    states = [
        {"entity_id": "sensor.xiaomi_m9_daa3_temperature", "state": "31.0", "attributes": {}},
        {"entity_id": "sensor.xiaomi_m9_daa3_relative_humidity", "state": "78", "attributes": {}},
        {"entity_id": "binary_sensor.pn_status", "state": "on", "attributes": {}},
        {"entity_id": "climate.xiaomi_m9_daa3_air_conditioner", "state": "off", "attributes": {"temperature": 25, "hvac_modes": ["off", "cool", "dry"]}},
        {"entity_id": "switch.ct3_ngoai_pn_kn_left", "state": "off", "attributes": {}},
    ]
    for speed in range(1, 7):
        states.append({"entity_id": f"script.fan_light_pn_kn_fan_{speed}", "state": "off", "attributes": {}})
    ha = FakeHA(states)
    runtime = FakeRuntime(ha)
    logic = LogicEngine(runtime)

    result = await logic.dry_run_profile("bedroom-climate-comfort")

    assert result["engine"] == "logic"
    assert result["execution"]["actions_executed"] == 0
    assert result["execution"]["read_tools_executed"] >= 1
    assert result["planned_actions"]
    assert runtime.calls == []
    assert ha._states["climate.xiaomi_m9_daa3_air_conditioner"]["state"] == "off"
    assert "Dự kiến" in result["response_preview"]
    assert any((x.get("arguments") or {}).get("data", {}).get("temperature") == 27 for x in result["planned_actions"])
    assert not any((x.get("arguments") or {}).get("data", {}).get("temperature") in {25, 26} for x in result["planned_actions"])


class RefusalAI:
    async def chat_with_trace(self, session_id, text, source="web"):
        from app.db import add_message
        add_message(session_id, "user", text, source)
        refusal = "Tôi là một mô hình ngôn ngữ, tôi không được thiết kế để trợ giúp về điều đó."
        add_message(session_id, "assistant", refusal, source)
        return {"text": refusal, "tools": []}


@pytest.mark.asyncio
async def test_generic_model_refusal_is_replaced_by_safe_clarification(isolated_db):
    ha = FakeHA([])
    router = LogicFirstOrchestrator(RefusalAI(), LogicEngine(FakeRuntime(ha)))

    result = await router.chat_with_trace("refusal", "Kiểm tra Home Assistant giúp tôi", "web")

    assert result["engine"] == "logic"
    assert result["reason"] == "ai_refusal_guard"
    assert "mô hình ngôn ngữ" not in result["text"].lower()
    assert "entity_id" in result["text"]

class DryRunFallbackAI(FakeAI):
    def __init__(self):
        super().__init__()
        self.dry_calls = 0

    async def dry_run_skill(self, name, user_text):
        self.dry_calls += 1
        return {"ok": True, "engine": "ai", "response_preview": "AI dry run"}


@pytest.mark.asyncio
async def test_orchestrator_skill_dry_run_prefers_logic_profile(isolated_db, tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile = json.loads(Path("config/logic_profiles/bedroom-climate-comfort.json").read_text(encoding="utf-8"))
    profile["rooms"] = [profile["rooms"][1]]
    (profiles / "bedroom-climate-comfort.json").write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(settings, "logic_profiles_dir", str(profiles))
    monkeypatch.setattr(settings, "user_logic_profiles_dir", str(tmp_path / "user-profiles"))
    monkeypatch.setattr(settings, "skills_dir", str(Path("config/skills").resolve()))
    user_skills = tmp_path / "user-skills"
    user_skills.mkdir()
    monkeypatch.setattr(settings, "user_skills_dir", str(user_skills))

    ha = FakeHA([
        {"entity_id": "sensor.xiaomi_m15_1480_temperature", "state": "28.2", "attributes": {}},
        {"entity_id": "sensor.xiaomi_m15_1480_relative_humidity", "state": "52", "attributes": {}},
        {"entity_id": "binary_sensor.ph_status", "state": "on", "attributes": {}},
        {"entity_id": "climate.xiaomi_m15_1480_air_conditioner", "state": "off", "attributes": {"temperature": 27, "hvac_modes": ["off", "cool"]}},
        {"entity_id": "switch.ct4_phong_soc_chip_l3", "state": "off", "attributes": {}},
        {"entity_id": "fan.sonoff_1000a827dd", "state": "off", "attributes": {"preset_mode": "off", "preset_modes": ["off", "low", "medium", "high"]}},
    ])
    ai = DryRunFallbackAI()
    router = LogicFirstOrchestrator(ai, LogicEngine(FakeRuntime(ha)))

    result = await router.dry_run_skill("bedroom-climate-comfort", "Kiểm tra hai phòng")

    assert result["engine"] == "logic"
    assert result["skill"]["name"] == "bedroom-climate-comfort"
    assert result["execution"]["actions_executed"] == 0
    assert ai.dry_calls == 0
