# HassMind v1.5.3 – Device State Report (Logic-First)

## Fixed

- Questions such as `ổ cắm bơm nước trạng thái ra sao` no longer mistakenly ask the user to pick between `switch.*` and `update.*` with the same friendly_name.
- Device-first status matching uses the operator-approved `21-devices.yaml` Knowledge index and **stable Home Assistant `device_id`**, not guessed entity_id prefixes or LLM predictions.
- Returns **every entity** linked by Home Assistant Entity Registry, displaying readable name, exact `entity_id`, current raw `state`, and unit when available. Disabled and hidden entities are still shown, labelled clearly; absent live state is explicitly reported as unavailable rather than invented.
- One live HA state snapshot plus cached registry metadata (configurable TTL), with no mutation, no calls to an AI model on successfully matched requests.
- Supports aliases and the common truncated phrase `ổ cắm bơm`; asks for clarification if multiple Devices match; honors explicit entity_id queries without expanding to the Device.
- User prompts requesting listings (`liệt kê`, `danh sách entity`, `thông số`, `báo cáo`) are also considered status questions.

## Security and compatibility

- The change is **read-only**. Device names do not become control authorization. Existing permissions and the direct-control route are unchanged.
- Knowledge Device import/review/approval and existing `20-entities.yaml` logic remain intact.
- When the Device no longer exists in HA Registry, HassMind alerts the user instead of guessing a matching entity.
- Previous v1.5.2 Device entries require **no migration**.

## Verification

- 175 Python tests and 33 Node.js tests passed in the available offline environment.
- The remaining integration tests import `openai` and `mcp`, which are not installed in this environment, and could not be run here. New device tests use a simulated HA Registry and states; acceptance against the user's live HA remains required.
