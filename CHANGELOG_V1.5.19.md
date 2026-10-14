# HassMind v1.5.19 - Compact, text-only note catalogue

## Fixed

- Commands requesting a list of notes no longer trigger image delivery over Zalo or inline photo galleries in Web Chat.
- The catalogue returns every saved note (no former 5-item/20-item truncation) as an indexed title, note ID and attachment count when nonzero.
- Listing uses one SQLite query with an attachment count rather than loading full notes, image URLs or private note bodies.
- Common Vietnamese list intents are recognized with or without accents, including variants such as "liet ke tat ca ghi chu" and "cho toi xem danh sach ghi chu".
- An empty search request asks for keywords instead of returning arbitrary notes and photos.
- The explicit list mode in the Zalo handler is text-only, including when some notes contain photos.
- Search and show still return the original note text and original attached images. The 60-second Zalo draft flow remains unchanged.

## Quality assurance

- Python: 307 passed, 1 skipped; 3 other test modules cannot collect without optional `openai` package in the test environment.
- Node JavaScript UI tests: 35 passed.
- Added full-catalogue, image-count, empty-catalogue, command-variation, and actual Zalo-handler regression tests.
- No production Zalo account was available for live verification.

The Zalo Server and Zalo HACS integrations do not need to be upgraded for this change.
