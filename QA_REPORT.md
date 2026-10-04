# HassMind v1.2.6 — QA report

## Automated tests

- Python unittest suite: PASS — 13 tests.
- Custom Integration CRUD + action persistence: PASS.
- Agent tool opt-in for Custom API Actions: PASS.
- Path-parameter declaration validation: PASS.
- Generic HTTP GET path/query execution via mocked transport: PASS.
- Generic HTTP POST JSON execution via mocked transport: PASS.
- Zalo rich-format preservation/normalization: PASS.
- Zalo FollowUp conversion: PASS.
- Zalo Markdown-table conversion: PASS.
- Zalo unsupported tag/HTML stripping: PASS.
- Zalo long-message splitting: PASS.
- HA state cache reuse/invalidation/WebSocket update tests: PASS.

## Static checks

- `python3 -m compileall -q app tests`: PASS.
- `node --check static/app.js`: PASS.
- `sh -n setup.sh`: PASS.
- YAML parse: `docker-compose.yml`, `docker-stack.yml`, `portainer-stack.yml`, `portainer-stack-opt.yml`, `config/mcp_servers.yaml`: PASS.
- Backend/frontend/package version synchronized to `1.2.6`: PASS.

## Telegram configuration smoke test

- Telegram present in Integration catalog: PASS.
- Save enabled/token/allowed-chat configuration: PASS.
- Runtime token stored separately from SQLite configuration: PASS.
- API view exposes only secret configured-state, not token value: PASS.
- Reset to stack/default: PASS.

## Security boundaries reviewed

- Custom API action cannot choose arbitrary Base URL at tool-call time: PASS.
- Custom API action cannot choose arbitrary HTTP method/path at tool-call time: PASS.
- Unknown arguments rejected against action schema: PASS.
- Secret values remain backend-side and are not placed in LLM tool arguments: PASS.
- Custom actions are not exposed to Agent unless `agent_enabled=true`: PASS.
- `mode=write` actions are excluded from read-only parallel execution: PASS.

## Upgrade notes

`setup.sh` is idempotent for integration-secret migration. Running the v1.2.6 script once is recommended if an existing Telegram token still lives at `secrets/telegram_bot_token.txt`; otherwise the Bot Token can be saved directly from Web Admin after deployment.
