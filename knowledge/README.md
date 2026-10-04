# HassMind Knowledge 1.3.2

Put static `.md`, `.txt`, `.yaml`, `.yml` or `.json` files here. Structured catalogs are indexed as entity/area/scene/script/reference/rules/procedures; existing prose remains searchable. Use Knowledge → Scan Knowledge to inspect files and proposals, then **Re-index** for an explicitly requested index refresh. Scan does not automatically modify content or index.

Examples are supplied separately in `examples/knowledge/`; replace sample entity/area IDs before copying. See `KNOWLEDGE_MIGRATION_VI.md` for schema, migration and deployment permissions. Keep only aliases, static metadata, instructions and reference material here. Current device values must come from Home Assistant. Do not store passwords or access tokens.

Content proposals require Review → Dry-run → explicit admin Approve. File hashes protect against stale drafts; original bytes are backed up in the SQLite DB for guarded rollback. Default Docker mounts this folder read-only; approved file edits need the optional Knowledge write mount and UID 10001 permissions.
