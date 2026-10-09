# HassMind v1.5.2 – Knowledge Device Browser

## New: Knowledge → Devices → Thêm từ Home Assistant

- Admin-only, authenticated device browser that reads Home Assistant Device, Entity and Area Registries live over WebSocket.
- Search by device name, area, manufacturer, model, integration, or HA device_id; filter by area, page 20 devices per screen.
- Select a device to see its registered entities and disabled/hidden indicators. Registry metadata is escaped before rendering.
- Optional custom display name and up to 20 aliases. Device selection persists a **stable match.device_id**; entity lists are discovered live and not duplicated in Knowledge YAML.
- Import creates a **Knowledge proposal** with snapshot/hash guards, never writes immediately. Only Dry-run + Approve commits, reindexes and allows Rollback.
- Prevent duplicate imports, stale devices, and stale file changes. Supports upgrading the legacy 21-devices.yaml sample while preserving its settings, aliases, notes and permissions.
- Knowledge index/search recognizes **device** records; Knowledge scan warns if an imported device disappears from HA registry.
- Existing entity Knowledge files, scheduler, event rules, admin session/CSRF and policy remain intact.

## API

- `GET /api/knowledge/devices` – admin session; live discovery with 30-second registry deadline.
- `POST /api/knowledge/devices/import` – admin session and CSRF; body: `device_id`, `name`, `aliases`; creates a pending proposal.

## Scope

Device records currently support grouping, discovery and Knowledge search. They do not override Home Assistant authorization or automatically map an ambiguous device name to a control entity. Deterministic actions still use existing exact-entity authorization until dedicated capability-based device resolution is implemented.

See `QA_V1.5.2.md` and `KNOWLEDGE_DEVICES_VI.md`.
