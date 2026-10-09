# QA – HassMind 1.5.3 Device State Report

## Offline checks

- Device status regression tests: 7 passed.
- Python suite excluding 4 integration modules requiring unavailable `openai`/`mcp` dependencies: 175 passed, 12 subtests passed.
- UI Node.js suite: 33 passed.
- `compileall` and archive structure validation performed.

## Live HA acceptance (not run here)

1. Upgrade the service image on the Swarm manager without resetting `/data` or `/knowledge` mounts.
2. Ensure **Knowledge → Devices** contains the actual pump Device with stable `match.device_id`. Re-index Knowledge if necessary.
3. Ask `ổ cắm bơm nước trạng thái ra sao`; verify one row for every HA Entity Registry member, including `switch`, `update`, `sensor`, `select`, `number`, `button`, disabled and hidden.
4. Verify numeric sensor `state` and `unit_of_measurement` against Home Assistant Developer Tools → States.
5. Ask `trạng thái switch.oc1_bom_nuoc?` to confirm an exact entity request does not expand to the whole Device.
6. Try two similarly named Devices and verify the correct resolution or clarification.
7. Verify control permissions have not changed.

Limitations: The report reflects the Registry and State API as actually returned by HA. Registry-only entities do not get an invented live state. No live network test was available during packaging.
