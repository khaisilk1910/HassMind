"""Device status must resolve an imported Device, never one of its same-name entities."""
import pytest
import yaml

from app import rag
from app.db import init_db
from app.logic_engine import LogicEngine, LogicFirstOrchestrator
from app.settings import settings
from test_logic_first_engine import FakeHA, FakeAI, FakeRuntime


@pytest.fixture()
def device_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "data" / "db.sqlite"))
    monkeypatch.setattr(settings, "knowledge_dir", str(tmp_path / "knowledge"))
    monkeypatch.setattr(settings, "logic_first_enabled", True)
    (tmp_path / "knowledge").mkdir()
    init_db()
    return tmp_path


def _seed(path, devices):
    (path / "knowledge" / "21-devices.yaml").write_text(yaml.safe_dump({
        "schema_version": 1, "kind": "hassmind_device_catalog", "devices": devices,
    }, allow_unicode=True), encoding="utf-8")
    assert rag.reindex_knowledge()["status"] == "ready"


def _pump():
    return {"key": "pump", "name": "Ổ cắm Bơm Nước", "aliases": ["bơm nước", "ổ điện bơm nước"],
            "area": "Bếp", "match": {"device_id": "pump-id"}, "entities": {"mode": "auto"}}


@pytest.mark.asyncio
async def test_full_device_report_ignores_duplicate_entity_friendly_names_and_ai(device_setup):
    _seed(device_setup, [_pump()])
    states = [
        {"entity_id": "switch.oc1_bom_nuoc", "state": "on", "attributes": {"friendly_name": "Ổ cắm Bơm Nước"}},
        {"entity_id": "update.oc1_bom_nuoc", "state": "off", "attributes": {"friendly_name": "Ổ cắm Bơm Nước"}},
        {"entity_id": "sensor.oc1_bom_nuoc_power", "state": "0", "attributes": {"friendly_name": "Power", "unit_of_measurement": "W"}},
        {"entity_id": "sensor.oc1_bom_nuoc_voltage", "state": "231", "attributes": {"friendly_name": "Voltage", "unit_of_measurement": "V"}},
        {"entity_id": "select.oc1_bom_nuoc_mode", "state": "auto", "attributes": {"friendly_name": "Mode"}},
        {"entity_id": "sensor.other_power", "state": "700", "attributes": {"friendly_name": "Power"}},
    ] + [{"entity_id": f"sensor.pump_extra_{i}", "state": str(i),
          "attributes": {"friendly_name": f"Extra metric {i}"}} for i in range(10)]
    entities = [
        {"device_id": "pump-id", "entity_id": "switch.oc1_bom_nuoc", "name": None},
        {"device_id": "pump-id", "entity_id": "update.oc1_bom_nuoc", "original_name": "Firmware"},
        {"device_id": "pump-id", "entity_id": "sensor.oc1_bom_nuoc_power", "original_name": "Power"},
        {"device_id": "pump-id", "entity_id": "sensor.oc1_bom_nuoc_voltage", "original_name": "Voltage"},
        {"device_id": "pump-id", "entity_id": "number.oc1_bom_nuoc_countdown", "original_name": "Countdown", "disabled_by": "user"},
        {"device_id": "pump-id", "entity_id": "select.oc1_bom_nuoc_mode", "original_name": "Mode", "hidden_by": "integration"},
        {"device_id": "other-id", "entity_id": "sensor.other_power"},
    ] + [{"device_id": "pump-id", "entity_id": f"sensor.pump_extra_{i}",
          "original_name": f"Extra metric {i}"} for i in range(10)]
    ha = FakeHA(states, entities=entities, devices=[{"id": "pump-id", "name": "Ổ cắm Bơm Nước"}])
    ai = FakeAI()
    router = LogicFirstOrchestrator(ai, LogicEngine(FakeRuntime(ha)))
    result = await router.chat_with_trace("test", "ổ cắm bơm nước trạng thái ra sao", "web")
    assert result["reason"] == "device_state_report"
    assert ai.calls == 0
    assert "16 entity" in result["text"]
    assert "15 có state" in result["text"]
    assert "sensor.oc1_bom_nuoc_power`: **0 W**" in result["text"]
    assert "sensor.oc1_bom_nuoc_voltage`: **231 V**" in result["text"]
    assert "switch.oc1_bom_nuoc`: **on**" in result["text"]
    assert "update.oc1_bom_nuoc`: **off**" in result["text"]
    assert "không có state" in result["text"]
    assert "đã vô hiệu hóa" in result["text"]
    assert "đang ẩn" in result["text"]
    assert "sensor.other_power" not in result["text"]
    assert all(f"sensor.pump_extra_{i}" in result["text"] for i in range(10))
    assert ha.state_calls == 1
    assert all(row["read_only"] and not row["side_effect"] for row in result["tools"])


@pytest.mark.asyncio
async def test_alias_and_omitted_final_word_read_full_device(device_setup):
    _seed(device_setup, [_pump()])
    ha = FakeHA([{"entity_id": "switch.oc1", "state": "off", "attributes": {"friendly_name": "Ổ cắm Bơm Nước"}}],
                entities=[{"device_id": "pump-id", "entity_id": "switch.oc1"}],
                devices=[{"id": "pump-id"}])
    engine = LogicEngine(FakeRuntime(ha))
    for query in ("bơm nước đang thế nào?", "ổ cắm bơm trạng thái ra sao"):
        result = await engine.try_handle(query)
        assert result.reason == "device_state_report"
        assert "switch.oc1" in result.text


@pytest.mark.asyncio
async def test_multiple_matching_devices_asks_without_reading_states(device_setup):
    other = {"key": "pump_2", "name": "Ổ cắm Bơm Nước 2", "aliases": ["bơm nước"],
             "match": {"device_id": "second-id"}, "entities": {"mode": "auto"}}
    _seed(device_setup, [_pump(), other])
    ha = FakeHA([], devices=[{"id": "pump-id"}, {"id": "second-id"}])
    result = await LogicEngine(FakeRuntime(ha)).try_handle("bơm nước trạng thái ra sao")
    assert result.reason == "ambiguous_device"
    assert "Ổ cắm Bơm Nước" in result.text and "Ổ cắm Bơm Nước 2" in result.text
    assert ha.state_calls == 0


@pytest.mark.asyncio
async def test_longer_device_name_beats_embedded_alias_but_not_two_devices(device_setup):
    other = {"key": "pump_2", "name": "Ổ cắm Bơm Nước 2", "aliases": ["bơm nước"],
             "match": {"device_id": "second-id"}, "entities": {"mode": "auto"}}
    _seed(device_setup, [_pump(), other])
    ha = FakeHA([{"entity_id": "switch.second", "state": "on", "attributes": {"friendly_name": "Ổ cắm Bơm Nước 2"}}],
                devices=[{"id": "pump-id"}, {"id": "second-id"}],
                entities=[{"device_id": "second-id", "entity_id": "switch.second"}])
    logic = LogicEngine(FakeRuntime(ha))
    single = await logic.try_handle("ổ cắm bơm nước 2 trạng thái ra sao")
    assert single.reason == "device_state_report"
    assert "switch.second" in single.text
    both = await logic.try_handle("ổ cắm bơm nước và ổ cắm bơm nước 2 trạng thái ra sao")
    assert both.reason == "ambiguous_device"


@pytest.mark.asyncio
async def test_explicit_entity_state_does_not_expand_to_device(device_setup):
    _seed(device_setup, [_pump()])
    ha = FakeHA([{"entity_id": "switch.oc1", "state": "on", "attributes": {"friendly_name": "Ổ cắm Bơm Nước"}}],
                entities=[{"device_id": "pump-id", "entity_id": "switch.oc1"}], devices=[{"id": "pump-id"}])
    result = await LogicEngine(FakeRuntime(ha)).try_handle("trạng thái switch.oc1 của bơm nước?")
    assert result.reason == "exact_state_query"
    assert "1 entity" not in result.text


@pytest.mark.asyncio
async def test_do_not_issue_device_commands_from_state_resolver(device_setup):
    _seed(device_setup, [_pump()])
    ha = FakeHA([{"entity_id": "switch.oc1", "state": "on", "attributes": {"friendly_name": "Ổ cắm Bơm Nước"}}],
                entities=[{"device_id": "pump-id", "entity_id": "switch.oc1"}], devices=[{"id": "pump-id"}])
    runtime = FakeRuntime(ha)
    result = await LogicEngine(runtime).try_handle("Tắt ổ cắm bơm nước")
    assert result.reason != "device_state_report"
    assert all("device_id" not in (call[1].get("target") or {}) for call in runtime.calls)


@pytest.mark.asyncio
async def test_missing_device_does_not_guess_other_entities(device_setup):
    _seed(device_setup, [_pump()])
    ha = FakeHA([{"entity_id": "switch.oc1", "state": "on", "attributes": {"friendly_name": "Ổ cắm Bơm Nước"}}],
                entities=[{"device_id": "pump-id", "entity_id": "switch.oc1"}], devices=[])
    result = await LogicEngine(FakeRuntime(ha)).try_handle("ổ cắm bơm nước trạng thái ra sao")
    assert result.reason == "device_registry_missing"
    assert "không còn" in result.text
    assert "switch.oc1" not in result.text
