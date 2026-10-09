"""Check AI model output is never treated as HA authority."""
import math
import pytest

from app.intent_parser import parse_device_status_intent


@pytest.mark.parametrize('raw, expected', [
    ('{"intent":"device_status","device_id":"known","confidence":0.99}', ("device_status", "known", 0.99)),
    ('```json\n{"intent":"device_status","device_id":"known","confidence":0.9}\n```', ("device_status", "known", 0.9)),
    ('{"intent":"device_status","device_id":"unknown","confidence":0.98}', ("device_status", "", 0.98)),
    ('{"intent":"execute","device_id":"known","confidence":1}', ("clarify", "", 0.0)),
    ('{"intent":"device_status","device_id":"known","confidence":"NaN"}', ("clarify", "", 0.0)),
    ('{"intent":"device_status","device_id":"known","confidence":true}', ("device_status", "known", 0.0)),
    ('{"intent":"device_status","device_id":"known","confidence":-4}', ("device_status", "known", 0.0)),
    ('{"intent":"device_status","device_id":"known","confidence":3}', ("device_status", "known", 1.0)),
    ('Sure, I will control it.', ("clarify", "", 0.0)),
    ('[]', ("clarify", "", 0.0)),
    ('{"intent":"other","device_id":"","confidence":0.8}', ("other", "", 0.8)),
])
def test_intent_parser(raw, expected):
    result = parse_device_status_intent(raw, {"known"})
    assert (result["intent"], result["device_id"], result["confidence"]) == expected


def test_reject_oversized_untrusted_response():
    result = parse_device_status_intent('x' * 6000, {"known"})
    assert result["intent"] == "clarify"
