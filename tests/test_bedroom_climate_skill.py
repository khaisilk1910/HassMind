from pathlib import Path

from app.policy import assert_service_allowed
from app.settings import settings
from app.skills import validate_skill_content

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "config" / "skills" / "bedroom-climate-comfort.md"


def test_bedroom_climate_skill_is_valid_and_has_confirmed_entities():
    raw = SKILL.read_text(encoding="utf-8")
    result = validate_skill_content(raw, expected_name="bedroom-climate-comfort")
    assert result["ok"], result["errors"]
    for entity_id in (
        "sensor.xiaomi_m9_daa3_temperature",
        "sensor.xiaomi_m9_daa3_relative_humidity",
        "climate.xiaomi_m9_daa3_air_conditioner",
        "switch.ct3_ngoai_pn_kn_left",
        "binary_sensor.pn_status",
        "sensor.xiaomi_m15_1480_temperature",
        "sensor.xiaomi_m15_1480_relative_humidity",
        "climate.xiaomi_m15_1480_air_conditioner",
        "switch.ct4_phong_soc_chip_l3",
        "fan.sonoff_1000a827dd",
        "binary_sensor.ph_status",
    ):
        assert f"`{entity_id}`" in raw
    assert "`.sensor.xiaomi_m15_1480_relative_humidity`" not in raw
    assert "25°C" in raw and "27°C" in raw
    assert "schedule_type: `window`" in raw
    assert "\"every_minutes\":30" in raw


def test_only_operator_allowlisted_fan_speed_scripts_are_directly_callable():
    old = settings.allow_script_entities
    try:
        settings.allow_script_entities = ",".join(
            f"script.fan_light_pn_kn_fan_{n}" for n in range(1, 7)
        )
        for n in range(1, 7):
            assert_service_allowed(
                "script",
                "turn_on",
                target={"entity_id": f"script.fan_light_pn_kn_fan_{n}"},
                data={},
            )
    finally:
        settings.allow_script_entities = old


def test_unapproved_scripts_and_script_variables_remain_blocked():
    old = settings.allow_script_entities
    try:
        settings.allow_script_entities = "script.fan_light_pn_kn_fan_1"
        try:
            assert_service_allowed(
                "script", "turn_on", target={"entity_id": "script.other"}, data={}
            )
            raise AssertionError("unapproved script must be blocked")
        except PermissionError:
            pass
        try:
            assert_service_allowed(
                "script",
                "turn_on",
                target={"entity_id": "script.fan_light_pn_kn_fan_1"},
                data={"variables": {"speed": 6}},
            )
            raise AssertionError("script variables must be blocked")
        except PermissionError:
            pass
    finally:
        settings.allow_script_entities = old
