# QA v1.5.2 – Knowledge Device Browser

## Tests

- Knowledge Device Catalog: grouping by HA device ID, 2 roles/sensors and disabled entities, draft/approve, duplicate prevention, external file races, absent HA Device, invalid aliases, and migrating old Device sample settings/notes.
- Admin API simulated integration: requires admin session and CSRF, rejects missing HA connection (503), publishes no mutations before approval, confirms indexed record after approval.
- JavaScript UI: accessible elements, escaped Home Assistant strings, disabled duplicate import, proper CSRF draft request and no silent approval.
- Previous Knowledge registry/proposals/governance/transactions/UI tests preserved.

Full Python suite in this sandbox: **225 passed, 12 subtests passed**, using local test-only stubs for unavailable `openai` and `mcp` imports (no real LLM/MCP or HA network calls). JavaScript suite: **33 passed**. Complete Docker build, GHCR publish, and testing against live Home Assistant were not possible in this sandbox.

## Key protections

1. No HA write endpoint is exposed by Device browser/import.
2. Exact HA device_id is verified when a draft is created; duplicates rejected.
3. Device Catalog is validated and applied only using the existing Knowledge proposal governance.
4. Old sample without device_id is migrated only for an unambiguous name + manufacturer/model match; original notes and permissions are kept.
5. A missing live Device raises a scan warning; state snapshots are excluded from files.
