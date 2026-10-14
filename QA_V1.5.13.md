# QA v1.5.13 (offline static + mocked integration)

- Python: 57 passed, 1 skipped (`test_notes.py`, `test_zalo_notes.py`, `test_zalo_transport.py`, `test_security_hardening.py`, `test_message_format.py`).
- Browser JavaScript: 35 passed (`tests/test_knowledge_ui.js`).
- Zalo Bot Server Node: 29 passed (`tests/*.test.js`, includes new CDN capture and token cache checks).
- Python module compilation and Node syntax checks: passed.
- Integration boundaries: private signed note retrieval -> `/api/sendImageByAccount`; authenticated short-lived `/api/incomingImage/:token`; per-session ordered photo buffering; CDN fallback.

Not covered: live Zalo photos, SDK delivery on the real account, Home Assistant add-on networking/reverse proxies, Docker production deployment, OAuth/cookie expiry timing. Rebuild both services and test on the actual host before relying on photo notes.
