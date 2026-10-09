# QA v1.5.4 - Logic-First AI Intent Fallback

## Offline

- Python tests: 198 passed; 12 subtests passed in the available environment.
- JavaScript UI tests: 33 passed.
- New AI routing tests: colloquial status phrase, validated Device ID, low-confidence clarification, ambiguous alias, original deterministic path, no accidental control, AI timeout, AI error, feature flag.
- Strict JSON parser tests: invalid/malicious IDs, malformed output, JSON code fences, NaN and boolean confidence, oversized response.
- Python compileall and JavaScript syntax checks passed.

## Not run in this environment

- 4 Python integration test modules rely on `openai` or `mcp` libraries not installed in the test container: `test_conditional_scheduler_notify.py`, `test_knowledge_routing.py`, `test_skill_dry_run.py`, `test_knowledge_api.py`.
- No real external OpenAI-compatible completion, live Home Assistant registry/state, Docker Swarm service, or reverse proxy was available for end-to-end verification.
- The screenshot's `Failed to fetch` does not establish a root cause; monitor reverse proxy and HassMind logs on the deployment.

## Acceptance checklist on deployment

1. Verify `/health` responds and OpenAI-compatible API is reachable from the HassMind container.
2. Ask `xem o cam bom nhu nao`: deterministic Device status path where recognized (zero AI calls).
3. Ask `o cam bom nhu nao` with a Device approved in `21-devices.yaml`: expected UI engine `AI -> Logic`, full entity report with live HA states.
4. Ask `co the tat o cam bom khong?`: normal AI agent, NOT automatic Device status report.
5. Disable/rename an entity: Device report must not invent a state.
6. If AI backend is unreachable: receive a time-bounded diagnostic; confirm an explicit `xem trang thai <device>` still works with HA online.
7. Verify `/data` and `/knowledge` persist across Swarm image upgrade.
