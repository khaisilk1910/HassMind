# HassMind v1.5.4 - Logic-First AI Intent Fallback

## Changes

- Added one bounded LLM intent-classification round for colloquial Device questions which the deterministic engine cannot classify, e.g. `o cam bom nhu nao`. The LLM receives only the user message and a single operator-approved Device identity; it cannot invoke tools in this step.
- A successful status classification (>= 0.85 and exact approved `device_id`) dispatches to the existing deterministic full-Device HA report. No LLM-provided live state is accepted.
- If classification is uncertain, ask a clarification; if Device identity is ambiguous, do not ask an LLM to guess. Non-status requests continue into the existing full AI agent.
- Questions asking HOW TO control, or asking permission to change a device, are not mistaken for status requests. Existing control allow/deny policy and approval requirements remain unchanged.
- Added a 12-second classifier timeout and 35-second timeout for interactive web full-agent fallback; errors become structured visible responses, with logs for diagnosis. Scheduler/system execution remains unchanged by the web-only chat timeout.
- Improved browser network failure messages for API fetch errors, preserving unsent chat text for retry.
- Added strict parsing and validation of model JSON responses, feature flag and environment configuration.
- Updated web cache-busting static asset versions.

## Config

- `LOGIC_AI_INTENT_ENABLED=true`
- `LOGIC_AI_INTENT_TIMEOUT_SECONDS=12`
- `LOGIC_AI_CHAT_TIMEOUT_SECONDS=35`

## Operational note

`Failed to fetch` is a browser/network or backend availability symptom, not an AI intent classification result. Test /health and server/proxy logs if it recurs. This release cannot verify the actual deployment/network problem offline.
