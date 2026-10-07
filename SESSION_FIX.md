# HassMind v1.1.1 - Web session fix

Fixes the web UI chat error `Cannot access 'sessionId' before initialization`.

Changes:
- Replaces the top-level `sessionId` lexical variable with `uiState.sessionId`.
- Persists a generated session ID immediately.
- Adds a session ID fallback for browsers without `crypto.randomUUID()`.
- Uses `uiState.token` consistently for API authentication.
- Bumps application/health version to `1.1.1`.
- Disables browser caching for `/` and shows `v1.1.1` in the web header so upgrades are easy to verify.
