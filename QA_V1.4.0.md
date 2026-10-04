# QA v1.4.0 — Bedroom Climate Comfort

## Scope
- New built-in skill `bedroom-climate-comfort` for Phòng ngủ and Phòng Sóc Chíp.
- Exact Home Assistant entity mapping supplied by the operator.
- Safe exact-script allowlist for six bedroom ceiling-fan speed scripts.
- Chat prompt library expanded from 21 to 22 skills.
- Version/cache bump to 1.4.0.

## Automated checks
- Python test suite: **177 passed + 12 subtests passed**.
- JavaScript UI tests: **29/29 passed**.
- `python -m compileall`: PASS.
- `node --check static/app.js`: PASS.
- Built-in skill validation: **22/22 valid**.
- Docker Compose / Docker Stack / Portainer YAML parse: PASS.

## Safety checks
- `script` is still not opened as a general direct-action domain.
- Only `script.turn_on` can use `ALLOW_SCRIPT_ENTITIES`.
- Exact `entity_id` target is required; area/device/broad targets are rejected.
- Service data/variables are rejected for allowlisted scripts.
- Non-allowlisted scripts remain blocked.
- Scenario Dry Run reports the allowlisted script action as permitted but executes **0** actions.
- Skill refuses automatic control when presence or environmental sensors are invalid/unavailable.
- Automatic climate setpoint is bounded to 25–27°C and the skill never selects `heat`.

## Environment note
The QA container does not have the production `openai` and `mcp` Python packages and is not connected to the user's Home Assistant instance. For import-only/full-suite QA, minimal temporary stubs were placed outside the source tree under `/mnt/data/qa_stubs`. They are not included in the release archive. No live HVAC/fan action was executed during QA.

## Operator-specific correction
The humidity entity supplied for Phòng Sóc Chíp had a leading dot (`.sensor...`). The skill uses the normalized Home Assistant entity ID `sensor.xiaomi_m15_1480_relative_humidity`.
